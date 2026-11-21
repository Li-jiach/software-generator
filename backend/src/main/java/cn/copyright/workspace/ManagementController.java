package cn.copyright.workspace;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import com.fasterxml.jackson.core.type.TypeReference;

@RestController
@RequestMapping("/api")
class ManagementController {
    final AuthService auth;
    final ProjectService projects;
    final OfficialCredentials credentials;
    ManagementController(AuthService auth,ProjectService projects,OfficialCredentials credentials){
        this.auth=auth;this.projects=projects;this.credentials=credentials;
    }
    Map<String,Object> admin(HttpServletRequest req){var u=auth.current(req);auth.requireAdmin(u);return u;}
    @GetMapping("/admin/official-credentials") Object officialAccount(HttpServletRequest req) {
        admin(req);
        var login = credentials.read();
        return Map.of("username", login.getOrDefault("username", ""), "configured", !login.isEmpty());
    }
    @PutMapping("/admin/official-credentials") Object saveOfficialAccount(@RequestBody Map<String,Object> body,HttpServletRequest req) {
        admin(req);
        credentials.save(body);
        return Map.of("ok", true);
    }
    @GetMapping("/admin/users") Object users(HttpServletRequest req){
        admin(req);return projects.db().queryForList("SELECT id,username,display_name AS displayName,role,department,enabled FROM users ORDER BY created_at");
    }
    @PostMapping("/admin/users") @Transactional Object createUser(@RequestBody Map<String,Object> b,HttpServletRequest req){
        admin(req);String username=ProjectService.required(b,"username",80),password=ProjectService.required(b,"password",72);
        if(!username.matches("[A-Za-z0-9_.-]{3,80}")||password.length()<12||password.getBytes(java.nio.charset.StandardCharsets.UTF_8).length>72)throw new ApiException(400,"账号需3位以上字母数字，密码需12位以上且不超过72字节");
        String role=role(b),name=ProjectService.required(b,"displayName",100),department=department(b);
        if(projects.db().queryForObject("SELECT COUNT(*) FROM users WHERE username=?",Integer.class,username)>0)throw new ApiException(409,"账号已存在");
        String id=UUID.randomUUID().toString();
        projects.db().update("INSERT INTO users(id,username,password_hash,display_name,role,department) VALUES(?,?,?,?,?,?)",id,username,new BCryptPasswordEncoder().encode(password),name,role,department);
        return Map.of("id",id);
    }
    String department(Map<String,Object> body) {
        String value = ProjectService.text(body, "department");
        if (!Set.of("研发中心","健康医疗大数据中心","人才评价与发展中心","培训中心").contains(value))
            throw new ApiException(400, "请选择有效部门");
        return value;
    }
    String role(Map<String,Object> b){String r=ProjectService.text(b,"role");if(!Set.of("admin","adminDept","research").contains(r))throw new ApiException(400,"角色不合法");return r;}
    @PutMapping("/admin/users/{id}") @Transactional Object updateUser(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req){
        var u=admin(req);String role=role(b);
        // Lock every account in consistent order, protecting concurrent last-admin changes.
        var rows=projects.db().queryForList("SELECT id,role,enabled FROM users ORDER BY id FOR UPDATE");
        var target=rows.stream().filter(x->id.equals(x.get("id"))).findFirst().orElseThrow(()->new ApiException(404,"账号不存在"));
        boolean enabled=!Boolean.FALSE.equals(b.get("enabled"));
        long admins=rows.stream().filter(x->"admin".equals(x.get("role"))&&Boolean.TRUE.equals(x.get("enabled"))).count();
        if("admin".equals(target.get("role"))&&Boolean.TRUE.equals(target.get("enabled"))&&(!enabled||!role.equals("admin"))&&admins<=1)throw new ApiException(409,"需要保留至少一个启用的管理员");
        projects.db().update("UPDATE users SET role=?,display_name=?,department=?,enabled=? WHERE id=?",role,ProjectService.required(b,"displayName",100),department(b),enabled,id);
        projects.db().update("DELETE FROM user_sessions WHERE user_id=?",id);
        return Map.of("ok",true,"self",id.equals(u.get("id")));
    }
    Map<String,Object> manual(String id){
        var rows=projects.db().queryForList("SELECT * FROM project_manuals WHERE project_id=?",id);
        if(rows.isEmpty())return Map.of("chapters",List.of(),"status","draft","revision",0,"comment","");
        var m=rows.get(0);m.put("chapters",projects.decode(m.get("chapters"),new TypeReference<List<Map<String,Object>>>(){}));return m;
    }
    @GetMapping("/projects/{id}/manual") Object getManual(@PathVariable String id,HttpServletRequest req){projects.raw(id,auth.current(req),false);return manual(id);}
    @PutMapping("/projects/{id}/manual") @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) Object saveManual(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req){
        var u=auth.current(req);projects.raw(id,u,true);var old=manual(id);projects.checkRevision(old,b.get("revision"));
        if("submitted".equals(old.get("status")))throw new ApiException(409,"手册审核中，暂不能修改");
        if(!(b.get("chapters") instanceof List<?> chapters)||chapters.size()>500)throw new ApiException(400,"手册章节格式不合法");
        for(var c:chapters)if(!(c instanceof Map<?,?> m)||ProjectService.text(m,"title").isBlank()||ProjectService.text(m,"body").isBlank())throw new ApiException(400,"章节标题与正文不能为空");
        String encoded=projects.encode(chapters);if(encoded.length()>5000000)throw new ApiException(400,"手册内容过大，请减少嵌入图片");
        projects.db().update("INSERT INTO project_manuals(project_id,chapters,status,revision,comment,updated_by) VALUES(?,?,'draft',1,'',?) ON DUPLICATE KEY UPDATE chapters=VALUES(chapters),status='draft',revision=revision+1,comment='',updated_by=VALUES(updated_by)",id,encoded,u.get("id"));
        projects.log(id,u,"保存操作手册","章节数 "+chapters.size());return manual(id);
    }
    @PostMapping("/projects/{id}/manual/submit") @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) Object submitManual(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req){
        var u=auth.current(req);projects.raw(id,u,true);var m=manual(id);projects.checkRevision(m,b.get("revision"));
        if(!Set.of("draft","returned").contains(m.get("status")))throw new ApiException(409,"当前手册不能重复提交");
        var chapters=(List<?>)m.get("chapters");
        if(chapters.isEmpty()||chapters.stream().anyMatch(c->!Boolean.TRUE.equals(((Map<?,?>)c).get("verified"))))throw new ApiException(422,"请确认所有章节无误后提交");
        projects.db().update("UPDATE project_manuals SET status='submitted',revision=revision+1,updated_by=? WHERE project_id=?",u.get("id"),id);
        projects.log(id,u,"提交手册审核","已进入审核管理");return manual(id);
    }
    @PostMapping("/projects/{id}/manual/review") @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED) Object reviewManual(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req){
        var u=admin(req);projects.raw(id,u,true);var m=manual(id);projects.checkRevision(m,b.get("revision"));
        String status=ProjectService.text(b,"status"),comment=ProjectService.text(b,"comment");
        if(!"submitted".equals(m.get("status")))throw new ApiException(409,"手册尚未提交或已审核");
        if(!Set.of("approved","returned").contains(status)||comment.length()>5000||("returned".equals(status)&&comment.isBlank()))throw new ApiException(400,"请选择审核结果，退回需填写原因");
        projects.db().update("INSERT INTO manual_reviews(project_id,revision,chapters,status,comment,reviewer_id) VALUES(?,?,?,?,?,?)",id,m.get("revision"),projects.encode(m.get("chapters")),status,comment,u.get("id"));
        projects.db().update("UPDATE project_manuals SET status=?,comment=?,revision=revision+1,updated_by=? WHERE project_id=?",status,comment,u.get("id"),id);
        projects.log(id,u,"审核操作手册",status+" "+comment);return manual(id);
    }
    @GetMapping("/admin/reviews") Object reviews(HttpServletRequest req){
        var u=admin(req);var result=new ArrayList<Map<String,Object>>();
        for(var p:projects.list(u)){
            var detail=projects.detail(String.valueOf(p.get("id")),u);
            detail.put("manual",manual(String.valueOf(p.get("id"))));
            detail.put("fieldHistory",projects.db().queryForList("SELECT r.id,r.field_key AS field,r.status,r.comment,r.form_version AS version,r.created_at AS time,u.display_name AS reviewer FROM field_reviews r JOIN users u ON u.id=r.reviewer_id WHERE project_id=? ORDER BY r.id DESC",p.get("id")));
            detail.put("manualHistory",projects.db().queryForList("SELECT r.id,r.status,r.comment,r.revision,r.created_at AS time,u.display_name AS reviewer FROM manual_reviews r JOIN users u ON u.id=r.reviewer_id WHERE project_id=? ORDER BY r.id DESC",p.get("id")));
            result.add(detail);
        }
        return result;
    }
    @GetMapping("/admin/reviews/{id}/manual/{reviewId}") Object manualSnapshot(@PathVariable String id,@PathVariable long reviewId,HttpServletRequest req){
        admin(req);
        var rows=projects.db().queryForList("SELECT chapters FROM manual_reviews WHERE project_id=? AND id=?",id,reviewId);
        if(rows.isEmpty())throw new ApiException(404,"手册审核版本不存在");
        return projects.decode(rows.get(0).get("chapters"),new TypeReference<List<Map<String,Object>>>(){});
    }
}
