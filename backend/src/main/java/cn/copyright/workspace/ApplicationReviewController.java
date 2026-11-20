package cn.copyright.workspace;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/projects/{id}")
class ApplicationReviewController {
    private final ProjectService projects;
    private final AuthService auth;

    ApplicationReviewController(ProjectService projects, AuthService auth) {
        this.projects = projects;
        this.auth = auth;
    }

    @GetMapping("/application-precheck")
    Object precheck(@PathVariable String id, HttpServletRequest req) {
        var user = auth.current(req);
        var project = projects.raw(id, user, false);
        return Map.of("checks", projects.applicationChecks(id, project), "canStart", canStart(user));
    }

    @PostMapping("/application-preview/start")
    @Transactional(isolation = Isolation.READ_COMMITTED)
    Object start(@PathVariable String id, HttpServletRequest req) {
        var user = auth.current(req);
        var project = projects.raw(id, user, true);
        if (!canStart(user)) throw new ApiException(403, "仅管理员或行政业务办可启动申报");
        var checks = projects.applicationChecks(id, project);
        if (checks.stream().anyMatch(check -> !"approved".equals(check.get("status"))))
            throw new ApiException(409, "四项材料均须审核通过后才能启动申报");
        projects.log(id, user, "启动申报流程预览", "当前四项材料均已审核通过");
        return Map.of("mode", "preview");
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
