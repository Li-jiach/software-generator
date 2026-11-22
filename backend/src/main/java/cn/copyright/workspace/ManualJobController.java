package cn.copyright.workspace;

import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/projects/{id}/manual-jobs")
class ManualJobController {
    private final ProjectService projects;
    private final AuthService auth;
    private final AttachmentStore store;
    private final AssistantBridge ai;

    ManualJobController(ProjectService projects, AuthService auth, AttachmentStore store, AssistantBridge ai) {
        this.projects = projects; this.auth = auth; this.store = store; this.ai = ai;
    }

    String owner(String id, HttpServletRequest request) {
        var user = auth.current(request);
        projects.raw(id, user, false);
        return user.get("id") + ":" + id;
    }

    String path(UUID job) { return "/manual/jobs/" + job; }

    String savedUrl(String id) {
        return projects.db().queryForList("SELECT entry_url FROM manual_capture_settings WHERE project_id=?",String.class,id)
            .stream().findFirst().orElse("");
    }

    @GetMapping("/settings")
    Object settings(@PathVariable String id, HttpServletRequest request) {
        owner(id, request);
        return Map.of("url",savedUrl(id));
    }

    @PutMapping("/settings")
    Object saveSettings(@PathVariable String id, @RequestBody Map<String,Object> body, HttpServletRequest request) {
        var user = auth.current(request);
        auth.requireAdmin(user);
        projects.raw(id,user,false);
        String url = ProjectService.text(body,"url");
        if (url.isEmpty()) {
            projects.db().update("DELETE FROM manual_capture_settings WHERE project_id=?",id);
        } else {
            try {
                var uri = URI.create(url);
                int port = uri.getPort();
                if (url.length()>500 || !"http".equals(uri.getScheme()) || port<1 || port>65535
                        || !("127.0.0.1:"+port).equals(uri.getRawAuthority())) throw new IllegalArgumentException();
            } catch (IllegalArgumentException ex) {
                throw new ApiException(422,"截图入口须使用 http://127.0.0.1:端口 的本机测试地址。");
            }
            projects.db().update("""
                INSERT INTO manual_capture_settings(project_id,entry_url) VALUES(?,?)
                ON DUPLICATE KEY UPDATE entry_url=VALUES(entry_url)
                """,id,url);
        }
        return Map.of("url",url);
    }

    @PostMapping
    Object start(@PathVariable String id, @RequestBody Map<String,Object> body, HttpServletRequest request) {
        String owner = owner(id, request);
        var metadata = sourceMetadata(id, owner, body);
        metadata.putAll(browserSettings(id, body));
        return ai.request("POST", "/manual/jobs", metadata);
    }

    @PostMapping("/preflight")
    Object testSite(@PathVariable String id, @RequestBody Map<String,Object> body, HttpServletRequest request) {
        String owner = owner(id, request);
        var settings = browserSettings(id, body);
        settings.put("owner", owner);
        return ai.request("POST", "/manual/jobs/preflight", settings);
    }

    @PostMapping("/source")
    Object startSource(@PathVariable String id, @RequestBody Map<String,Object> body, HttpServletRequest request) {
        String owner = owner(id, request);
        var metadata = sourceMetadata(id, owner, body);
        metadata.putAll(browserSettings(id, body));
        return ai.request("POST", "/manual/jobs/source", metadata);
    }

    @PostMapping("/reset")
    Object reset(@PathVariable String id, HttpServletRequest request) {
        return ai.request("POST", "/manual/jobs/reset", Map.of("owner", owner(id, request)));
    }

    @PostMapping("/{job}/generate")
    Object generate(@PathVariable String id, @PathVariable UUID job, @RequestBody Map<String,Object> body, HttpServletRequest request) {
        String owner = owner(id, request);
        var settings = browserSettings(id, body);
        settings.put("owner", owner);
        return ai.request("POST", path(job) + "/generate", settings);
    }

    Map<String,Object> browserSettings(String id, Map<String,Object> body) {
        String url = savedUrl(id);
        if (url.isBlank() || !url.equals(ProjectService.text(body,"url")))
            throw new ApiException(422,"请先由管理员保存本项目的截图入口，再开始分析。");
        if (!Boolean.TRUE.equals(body.get("browserReady")))
            throw new ApiException(422,"请先勾选 Chrome 测试站点确认。");
        return new LinkedHashMap<>(Map.of("url", url, "browserReady", true));
    }

    Map<String,Object> sourceMetadata(String id, String owner, Map<String,Object> body) {
        String fileId = ProjectService.required(body, "fileId", 36);
        var files = projects.db().queryForList("SELECT name, storage_path FROM attachments WHERE project_id=? AND id=? AND deleted=FALSE", id, fileId);
        if (files.isEmpty()) throw new ApiException(404,"未找到该项目的源码附件");
        var file = files.get(0);
        if (!ProjectService.text(file,"name").toLowerCase(Locale.ROOT).endsWith(".zip") || file.get("storage_path")==null)
            throw new ApiException(400,"请选择该项目已上传的源码文件夹或 ZIP");
        var project = projects.db().queryForMap("SELECT name,version,description FROM projects WHERE id=?",id);
        var form = projects.form(id);
        var basic = new LinkedHashMap<String,String>();
        for (var f : projects.fields()) {
            String value = form.getOrDefault(String.valueOf(f.get("id")), "");
            if (!value.isBlank()) basic.put(String.valueOf(f.get("label")), value);
        }
        return new LinkedHashMap<>(Map.of("owner",owner,"archive",store.path(file).toString(),
            "project",project,"basic",basic));
    }

    @GetMapping
    Object latest(@PathVariable String id, HttpServletRequest request) {
        return ai.request("POST","/manual/jobs/latest",Map.of("owner",owner(id,request)));
    }

    @GetMapping("/{job}")
    Object status(@PathVariable String id, @PathVariable UUID job, HttpServletRequest request) {
        return ai.request("POST",path(job)+"/status",Map.of("owner",owner(id,request)));
    }

    @PostMapping("/{job}/capture")
    Object capture(@PathVariable String id, @PathVariable UUID job, HttpServletRequest request) {
        return ai.request("POST",path(job)+"/capture",Map.of("owner",owner(id,request),"url",savedUrl(id)));
    }

    @DeleteMapping("/{job}")
    Object cancel(@PathVariable String id, @PathVariable UUID job, HttpServletRequest request) {
        return ai.request("POST",path(job)+"/cancel",Map.of("owner",owner(id,request)));
    }

    @GetMapping("/{job}/{kind:word|plan}")
    ResponseEntity<byte[]> download(@PathVariable String id, @PathVariable UUID job, @PathVariable String kind, HttpServletRequest request) {
        String owner = owner(id, request);
        if (kind.equals("word")) throw new ApiException(428,"请先确认生成手册的参考用途");
        return downloadFile(job, kind, owner);
    }

    @PostMapping("/{job}/word")
    ResponseEntity<byte[]> downloadWord(@PathVariable String id, @PathVariable UUID job,
                                        @RequestBody Map<String,Object> body, HttpServletRequest request) {
        String owner = owner(id, request);
        if (!Boolean.TRUE.equals(body.get("acknowledged"))) throw new ApiException(428,"请先确认生成手册的参考用途");
        return downloadFile(job, "word", owner);
    }

    private ResponseEntity<byte[]> downloadFile(UUID job, String kind, String owner) {
        byte[] bytes = ai.download(path(job)+"/"+kind, Map.of("owner",owner));
        boolean word = kind.equals("word");
        return ResponseEntity.ok().contentType(MediaType.parseMediaType(word ?
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "application/json"))
            .header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(word?"操作手册.docx":"截图计划.json",StandardCharsets.UTF_8).build().toString())
            .body(bytes);
    }
}
