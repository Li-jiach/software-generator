package cn.copyright.workspace;

import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.time.Instant;
import java.nio.charset.StandardCharsets;
import org.springframework.http.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/projects/{id}")
class ApplicationReviewController {
    private final ProjectService projects;
    private final AuthService auth;

    private final OfficialCredentials credentials;
    private final AttachmentStore store;
    private final Map<String, Launch> launches = new ConcurrentHashMap<>();

    private record Launch(UUID ticket, String projectId, Object revision, Instant expiresAt) {}

    ApplicationReviewController(ProjectService projects, AuthService auth, OfficialCredentials credentials, AttachmentStore store) {
        this.projects = projects;
        this.auth = auth;
        this.credentials = credentials;
        this.store = store;
    }

    @GetMapping("/application-precheck")
    Object precheck(@PathVariable String id, HttpServletRequest req) {
        var user = auth.current(req);
        var project = projects.raw(id, user, false);
        return Map.of("checks", projects.applicationChecks(id, project), "canStart", canStart(user), "fieldIssues", projects.officialFieldIssues(id));
    }

    @PostMapping("/application-preview/start")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    Object start(@PathVariable String id, HttpServletRequest req) {
        var user = auth.current(req);
        approvedProject(id, user);
        projects.log(id, user, "启动申报流程预览", "当前四项材料均已审核通过");
        return Map.of("mode", "preview");
    }

    @PostMapping("/official-application/start")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    Object startOfficial(@PathVariable String id, HttpServletRequest req) {
        var user = auth.current(req);
        var project = approvedProject(id, user);
        Instant now = Instant.now();
        launches.values().removeIf(launch -> !launch.expiresAt().isAfter(now));
        var launch = new Launch(UUID.randomUUID(), id, project.get("revision"), now.plusSeconds(120));
        launches.put(AuthService.hash(auth.cookie(req)), launch);
        return Map.of("ticket", launch.ticket());
    }

    @PostMapping("/official-application/consume")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    Object consumeOfficial(@PathVariable String id, @RequestBody Map<String,Object> body, HttpServletRequest req) {
        var user = auth.current(req);
        String session = AuthService.hash(auth.cookie(req));
        var launch = launches.get(session);
        if (launch == null || !launch.projectId().equals(id) ||
            !launch.ticket().toString().equals(ProjectService.text(body, "ticket")) ||
            !launch.expiresAt().isAfter(Instant.now()) || !launches.remove(session, launch))
            throw new ApiException(409, "启动凭证已失效，请从工作台重新启动申报");

        var project = approvedProject(id, user);
        projects.checkRevision(project, launch.revision());
        var login = "admin".equals(user.get("role")) ? credentials.read() : Map.<String,String>of();
        projects.log(id, user, "启动官网填报", "已向 Ui.Vision 提供当前审核版本");
        return Map.of("form", projects.officialForm(id), "login", login, "materials", officialMaterials(id));
    }

    @GetMapping("/official-application/materials/{kind}/{fileId}/pdf")
    ResponseEntity<byte[]> materialPdf(@PathVariable String id, @PathVariable String kind,
            @PathVariable String fileId, @RequestParam String sha256, HttpServletRequest req) throws IOException {
        var user = auth.current(req);
        var project = approvedProject(id, user, false);
        var file = officialMaterials(id).get(kind);
        if (file == null || !fileId.equals(file.get("id")) || !sha256.equals(file.get("sha256")))
            throw new ApiException(409, "审核附件已变化，请重新启动申报");
        String name = String.valueOf(file.get("name"));
        String suffix = name.substring(Math.max(name.lastIndexOf('.'), 0)).toLowerCase(Locale.ROOT);
        byte[] original;
        if ("manual".equals(kind) && "chapters".equals(fileId)) {
            original = approvedManualChapters(id);
            suffix = ".chapters";
        } else {
            if (!suffix.matches("\\.[a-z0-9]{1,12}")) throw new ApiException(422, "附件扩展名无法转换");
            var rows = projects.db().queryForList(
                "SELECT storage_path, content FROM attachments WHERE project_id=? AND id=? AND deleted=FALSE", id, fileId);
            if (rows.isEmpty()) throw new ApiException(409, "审核附件已变化，请重新启动申报");
            try (var input = store.resource(rows.get(0)).getInputStream()) {
                original = input.readNBytes(20 * 1024 * 1024 + 1);
            }
        }
        try {
            var digest = java.security.MessageDigest.getInstance("SHA-256").digest(original);
            if (!sha256.equals(HexFormat.of().formatHex(digest)))
                throw new ApiException(409, "附件与审核版本不一致，或已超过 20 MB");
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
        boolean excerpt = Set.of("source", "manual").contains(kind) &&
            !"例外交存".equals(projects.form(id).get(kind + "Deposit"));
        byte[] pdf = store.ai.officialPdf(suffix, original, excerpt);
        projects.checkRevision(approvedProject(id, user, false), project.get("revision"));
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
            .contentType(MediaType.APPLICATION_PDF).body(pdf);
    }

    private byte[] approvedManualChapters(String id) {
        var rows = projects.db().queryForList("""
            SELECT chapters FROM project_manuals
            WHERE project_id=? AND status='approved' AND attachment_id IS NULL AND JSON_LENGTH(chapters)>0
            """, String.class, id);
        return rows.isEmpty() ? new byte[0] : rows.get(0).getBytes(StandardCharsets.UTF_8);
    }

    private Map<String, Map<String, Object>> officialMaterials(String id) {
        var materials = new LinkedHashMap<String, Map<String, Object>>();
        var approvedIds = new LinkedHashMap<String, Object>();
        var manuals = projects.db().queryForList(
            "SELECT attachment_id FROM project_manuals WHERE project_id=? AND status='approved'", id);
        if (!manuals.isEmpty()) approvedIds.put("manual", manuals.get(0).get("attachment_id"));
        for (String kind : ProjectService.APPLICATION_MATERIALS)
            approvedIds.put(kind, projects.materialReview(id, kind).get("attachmentId"));
        for (var file : projects.files(id)) {
            for (var approved : approvedIds.entrySet()) {
                if (Objects.equals(file.get("id"), approved.getValue())) {
                    materials.put(approved.getKey(), Map.of(
                        "id", file.get("id"), "name", file.get("name"), "sha256", file.get("sha256"),
                        "size", file.get("size")));
                }
            }
        }
        if (!materials.containsKey("manual")) {
            byte[] chapters = approvedManualChapters(id);
            if (chapters.length > 0) {
                materials.put("manual", Map.of("id", "chapters", "name", "操作手册.pdf",
                    "sha256", AuthService.hash(new String(chapters, StandardCharsets.UTF_8)), "size", chapters.length));
            }
        }
        return materials;
    }

    private Map<String,Object> approvedProject(String id, Map<String,Object> user) {
        return approvedProject(id, user, true);
    }

    private Map<String,Object> approvedProject(String id, Map<String,Object> user, boolean lock) {
        if (!canStart(user)) throw new ApiException(403, "仅管理员或行政业务办可启动申报");
        var project = projects.raw(id, user, lock);
        if (projects.applicationChecks(id, project).stream().anyMatch(check -> !"approved".equals(check.get("status"))))
            throw new ApiException(409, "四项材料均须审核通过后才能启动申报");
        var fieldIssues = projects.officialFieldIssues(id);
        if (!fieldIssues.isEmpty())
            throw new ApiException(422, fieldIssues.get(0).get("message") + "，请补填并重新审核");
        return project;
    }

    @PostMapping("/application-materials/{kind}/submit")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    Object submit(@PathVariable String id, @PathVariable String kind, @RequestBody Map<String,Object> body, HttpServletRequest req) {
        var user = auth.current(req);
        projects.raw(id, user, true);
        String category = ProjectService.materialCategory(kind);
        String attachmentId = ProjectService.required(body, "attachmentId", 36);
        var attachment = projects.materialCandidates(id, category).stream()
            .filter(file -> attachmentId.equals(file.get("id"))).findFirst()
            .orElseThrow(() -> new ApiException(422, "请选择当前项目对应分类的最新附件"));
        var current = projects.materialReview(id, kind);
        if (attachmentId.equals(current.get("attachmentId")) && Set.of("approved", "submitted").contains(current.get("status")))
            throw new ApiException(409, "此附件版本已送审或已通过");
        projects.db().update("""
            INSERT INTO application_material_reviews(project_id,kind,attachment_id,comment,submitted_by)
            VALUES(?,?,?,'',?)
            """, id, kind, attachmentId, user.get("id"));
        projects.log(id, user, "提交" + category + "审核", attachment.get("name") + " v" + attachment.get("version"));
        return projects.materialReview(id, kind);
    }

    @PostMapping("/application-materials/{kind}/review")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    Object review(@PathVariable String id, @PathVariable String kind, @RequestBody Map<String,Object> body, HttpServletRequest req) {
        var user = auth.current(req);
        auth.requireAdmin(user);
        projects.raw(id, user, true);
        var current = projects.materialReview(id, kind);
        if (!"submitted".equals(current.get("status")) ||
            !String.valueOf(current.get("reviewId")).equals(ProjectService.text(body, "reviewId")))
            throw new ApiException(409, "材料审核版本已变化，请刷新后重试");
        String status = ProjectService.text(body, "status");
        String comment = ProjectService.text(body, "comment");
        if (!Set.of("approved", "returned").contains(status) || comment.length() > 5000 ||
            ("returned".equals(status) && comment.isBlank()))
            throw new ApiException(400, "请选择审核结果，退回需填写原因");
        projects.db().update("""
            UPDATE application_material_reviews SET status=?,comment=?,reviewer_id=?,reviewed_at=CURRENT_TIMESTAMP(3)
            WHERE id=?
            """, status, comment, user.get("id"), current.get("reviewId"));
        projects.log(id, user, ("approved".equals(status) ? "通过" : "退回") + ProjectService.materialCategory(kind) + "审核",
            current.get("name") + " v" + current.get("version") + (comment.isBlank() ? "" : " · " + comment));
        return projects.materialReview(id, kind);
    }

    private boolean canStart(Map<String,Object> user) {
        return Set.of("admin", "adminDept").contains(user.get("role"));
    }
}
