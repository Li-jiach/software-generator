package cn.copyright.workspace;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import java.time.*;
import java.util.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class ProjectService {
    static final List<String> APPLICATION_MATERIALS = List.of("source", "ownership");
    private static final String LATEST_ATTACHMENT = """
        NOT EXISTS (SELECT 1 FROM attachments newer
                    WHERE newer.project_id=a.project_id AND newer.name=a.name AND newer.version>a.version)
        """;
    final JdbcTemplate db; final ObjectMapper json; final AuthService auth;
    List<Map<String,Object>> fields;
    ProjectService(JdbcTemplate db,ObjectMapper json,AuthService auth) { this.db=db; this.json=json; this.auth=auth; }
    @PostConstruct void metadata() throws Exception { fields=json.readValue(new ClassPathResource("fields.json").getInputStream(), new TypeReference<>(){}); }
    JdbcTemplate db() { return db; }
    List<Map<String,Object>> fields() { return fields; }
    String encode(Object value) { try {return json.writeValueAsString(value);} catch(Exception e){throw new IllegalArgumentException("JSON格式错误");} }
    <T> T decode(Object value, TypeReference<T> type) { try{return json.readValue(String.valueOf(value),type);}catch(Exception e){throw new IllegalStateException("存储数据格式错误",e);} }
    static String text(Map<?,?> data,String key) {Object v=data.get(key);return v==null?"":String.valueOf(v).trim();}
    static String required(Map<?,?> data,String key,int max) {String v=text(data,key);if(v.isEmpty()||v.length()>max)throw new ApiException(400,key+"不能为空且不能超过"+max+"字");return v;}
    boolean canView(Map<String,Object> p,Map<String,Object> u) {
        List<String> roles=decode(p.get("allowed_roles"),new TypeReference<>(){});
        return "admin".equals(u.get("role"))||roles.contains(String.valueOf(u.get("role")));
    }
    Map<String,Object> raw(String id,Map<String,Object> u,boolean lock) {
        var ps=db.queryForList("SELECT * FROM projects WHERE id=? AND archived=FALSE"+(lock?" FOR UPDATE":""),id);
        if(ps.isEmpty())throw new ApiException(404,"项目不存在或已归档");
        var p=ps.get(0);if(!canView(p,u))throw new ApiException(403,"无权访问该项目");return p;
    }
    List<Map<String,Object>> list(Map<String,Object> u) {
        var result=new ArrayList<Map<String,Object>>();
        for(var p:db.queryForList("SELECT * FROM projects WHERE archived=FALSE ORDER BY updated_at DESC"))if(canView(p,u))result.add(summary(p));
        return result;
    }
    Map<String,Object> summary(Map<String,Object> p) {
        var m=new LinkedHashMap<String,Object>();
        m.put("id",p.get("id"));m.put("name",p.get("name"));m.put("version",p.get("version"));m.put("dept",p.get("department"));m.put("owner",p.get("owner"));m.put("description",p.get("description"));m.put("formStatus",formStatus(p));m.put("revision",p.get("revision"));m.put("formVersion",p.get("form_version"));m.put("allowedRoles",decode(p.get("allowed_roles"),new TypeReference<List<String>>(){}));m.put("created",p.get("created_at"));m.put("updated",p.get("updated_at"));
        m.put("fileCount",db.queryForObject("SELECT COUNT(*) FROM attachments WHERE project_id=? AND deleted=FALSE",Integer.class,p.get("id")));
        return m;
    }
    Map<String,String> form(String id) {
        var f=new LinkedHashMap<String,String>();
        for(var r:db.queryForList("SELECT field_key,field_value FROM project_fields WHERE project_id=?",id))f.put(String.valueOf(r.get("field_key")),String.valueOf(r.get("field_value")));
        return f;
    }
    Map<String,Object> reviews(String id,Map<String,String> f) {
        var result=new LinkedHashMap<String,Object>();
        var rs=db.queryForList("SELECT r.field_key,r.field_value_hash,r.status,r.comment,r.created_at AS time,u.display_name AS reviewer FROM field_reviews r JOIN users u ON u.id=r.reviewer_id WHERE r.project_id=? AND r.id IN (SELECT MAX(id) FROM field_reviews WHERE project_id=? GROUP BY field_key)",id,id);
        for(var r:rs)if(AuthService.hash(f.getOrDefault(String.valueOf(r.get("field_key")),"")).equals(r.get("field_value_hash")))result.put(String.valueOf(r.get("field_key")),r);
        return result;
    }
    Map<String,Object> detail(String id,Map<String,Object> u) {
        var p=raw(id,u,false);var m=summary(p);var f=form(id);m.put("form",f);m.put("formReviews",reviews(id,f));
        m.put("files",files(id));
        m.put("applicationMaterials", APPLICATION_MATERIALS.stream().map(kind -> {
            var material = materialReview(id, kind);
            material.put("candidates", materialCandidates(id, materialCategory(kind)));
            return material;
        }).toList());
        m.put("assistantReferenceFields",db.queryForList("SELECT field_key FROM assistant_reference_fields WHERE project_id=?",String.class,id));
        m.put("activity",db.queryForList("SELECT a.id,a.title,a.detail,a.created_at AS time,u.display_name AS actor,u.role FROM activity_logs a JOIN users u ON u.id=a.actor_id WHERE project_id=? ORDER BY a.id DESC LIMIT 100",id));
        m.put("records",db.queryForList("SELECT r.id,r.status,r.reference_no AS referenceNo,r.occurred_at AS occurredAt,r.note,r.evidence_id AS evidenceId,u.display_name AS actor FROM application_records r JOIN users u ON u.id=r.created_by WHERE r.project_id=? ORDER BY r.occurred_at DESC,r.created_at DESC",id));
        m.put("validation",validate(f));return m;
    }
    List<Map<String,Object>> files(String id) {return db.queryForList("SELECT id,name,category AS type,content_type AS contentType,byte_size AS size,version,content_sha256 AS sha256,extraction_warning AS warning,created_at AS uploaded FROM attachments WHERE project_id=? AND deleted=FALSE ORDER BY created_at DESC,version DESC",id);}
    static String materialCategory(String kind) {
        return switch (kind) {
            case "source" -> "源程序鉴别材料";
            case "ownership" -> "权属材料";
            default -> throw new ApiException(404, "未知申报材料");
        };
    }

    List<Map<String,Object>> materialCandidates(String id, String category) {
        return db.queryForList("""
            SELECT a.id,a.name,a.version FROM attachments a
            WHERE a.project_id=? AND a.category=? AND a.deleted=FALSE AND
            """ + LATEST_ATTACHMENT + " ORDER BY a.created_at DESC", id, category);
    }

    Map<String,Object> materialReview(String id, String kind) {
        String category = materialCategory(kind);
        String label = "source".equals(kind) ? "已生成源程序鉴别材料" : "权属证明附件已关联";
        var rows = db.queryForList("""
            SELECT r.id AS reviewId,r.attachment_id AS attachmentId,a.name,a.version,
                   r.comment,r.created_at AS submittedAt,r.reviewed_at AS reviewedAt,
                   submitter.display_name AS submitter,reviewer.display_name AS reviewer,
                   CASE WHEN r.invalidated=FALSE AND a.deleted=FALSE AND a.category=? AND
            """ + LATEST_ATTACHMENT + """
                   THEN r.status ELSE 'stale' END AS status
            FROM application_material_reviews r
            JOIN attachments a ON a.id=r.attachment_id
            JOIN users submitter ON submitter.id=r.submitted_by
            LEFT JOIN users reviewer ON reviewer.id=r.reviewer_id
            WHERE r.project_id=? AND r.kind=? ORDER BY r.id DESC LIMIT 1
            """, category, id, kind);
        var result = rows.isEmpty() ? new LinkedHashMap<String,Object>() : rows.get(0);
        result.putIfAbsent("status", "draft");
        result.put("kind", kind);
        result.put("label", label);
        result.put("category", category);
        return result;
    }

    List<Map<String,Object>> applicationChecks(String id, Map<String,Object> project) {
        var checks = new ArrayList<Map<String,Object>>();
        checks.add(Map.of("kind", "form", "label", "人工填报全部核实", "status", formStatus(project)));
        var manual = db.queryForList("SELECT status FROM project_manuals WHERE project_id=?", String.class, id);
        checks.add(Map.of("kind", "manual", "label", "操作手册已核实", "status", manual.isEmpty() ? "draft" : manual.get(0)));
        for (String kind : APPLICATION_MATERIALS) checks.add(materialReview(id, kind));
        return checks;
    }

    void log(String id,Map<String,Object> u,String title,String detail) {db.update("INSERT INTO activity_logs(project_id,actor_id,title,detail) VALUES(?,?,?,?)",id,u.get("id"),title,detail);}
    void bump(String id) {db.update("UPDATE projects SET revision=revision+1,updated_at=CURRENT_TIMESTAMP(3) WHERE id=?",id);}
    void checkRevision(Map<String,Object> p,Object revision) {if(revision==null||!String.valueOf(p.get("revision")).equals(String.valueOf(revision)))throw new ApiException(409,"项目已被其他人修改，请刷新后重试");}

    @Transactional Map<String,Object> create(Map<String,Object> body,Map<String,Object> u) {
        String name=required(body,"name",200),version=required(body,"version",80),dept=required(body,"dept",100),owner=required(body,"owner",100);
        var roles=List.of("adminDept","research");
        String id="IP-"+Year.now()+"-"+UUID.randomUUID().toString().substring(0,8).toUpperCase();
        db.update("INSERT INTO projects(id,name,version,department,owner,description,allowed_roles,created_by) VALUES(?,?,?,?,?,?,?,?)",id,name,version,dept,owner,text(body,"description"),encode(roles),u.get("id"));
        for(var e:Map.of("fullName",name,"version",version,"acquisition","原始取得","rights","全部权利","softwareType","应用软件","descriptionType","原创","devMode","单独开发","publishStatus","未发表","originalCopies","1","duplicateCopies","0").entrySet())putField(id,e.getKey(),e.getValue(),u);
        log(id,u,"创建软著项目",name+" "+version);return detail(id,u);
    }
    @Transactional Map<String,Object> update(String id,Map<String,Object> body,Map<String,Object> u) {
        var p=raw(id,u,true);auth.requireAdmin(u);checkRevision(p,body.get("revision"));
        String name=required(body,"name",200),version=required(body,"version",80);
        String dept=required(body,"dept",100),owner=required(body,"owner",100);
        var roles=body.getOrDefault("allowedRoles",List.of("adminDept","research"));
        if(!(roles instanceof List<?> r)||r.stream().anyMatch(x->!Set.of("adminDept","research").contains(x)))throw new ApiException(400,"项目授权角色不合法");
        boolean identityChanged=!name.equals(p.get("name"))||!version.equals(p.get("version"));
        if(identityChanged&&"submitted".equals(p.get("form_status")))throw new ApiException(409,"审核中不能修改软件名称或版本");
        db.update("UPDATE projects SET name=?,version=?,department=?,owner=?,description=?,allowed_roles=?,revision=revision+1,form_status=?,form_version=form_version+? WHERE id=?",name,version,dept,owner,text(body,"description"),encode(roles),identityChanged?"draft":p.get("form_status"),identityChanged?1:0,id);
        var existing=form(id);
        if(!name.equals(existing.get("fullName")))clearAssistantReference(id,"fullName");
        if(!version.equals(existing.get("version")))clearAssistantReference(id,"version");
        putField(id,"fullName",name,u);putField(id,"version",version,u);log(id,u,"更新项目资料",name);return detail(id,u);
    }
    @Transactional void archive(String id,Map<String,Object> u) {raw(id,u,true);auth.requireAdmin(u);db.update("UPDATE projects SET archived=TRUE,revision=revision+1 WHERE id=?",id);log(id,u,"项目归档","项目已归档，数据库中保留原数据");}
    void putField(String id,String key,String value,Map<String,Object> u) {
        db.update("INSERT INTO project_fields(project_id,field_key,field_value,updated_by) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE field_value=VALUES(field_value),updated_by=VALUES(updated_by)",id,key,value,u.get("id"));
    }
    void clearAssistantReference(String id,String key) {
        db.update("DELETE FROM assistant_reference_fields WHERE project_id=? AND field_key=?",id,key);
    }
    @Transactional Map<String,Object> saveForm(String id,Map<String,Object> body,Map<String,Object> u) {
        return saveForm(id,body,u,false);
    }
    @Transactional Map<String,Object> saveAssistantForm(String id,Map<String,Object> body,Map<String,Object> u) {
        return saveForm(id,body,u,true);
    }
    private Map<String,Object> saveForm(String id,Map<String,Object> body,Map<String,Object> u,boolean assistant) {
        var p=raw(id,u,true);checkRevision(p,body.get("revision"));
        if("submitted".equals(p.get("form_status")))throw new ApiException(409,"表单审核中，请等待审核或退回");
        if(!(body.get("fields") instanceof Map<?,?> values))throw new ApiException(400,"缺少填报字段");
        var existing=form(id);var changed=new ArrayList<String>();
        for(var entry:values.entrySet()) {
            String key=String.valueOf(entry.getKey());var field=fields.stream().filter(x->key.equals(x.get("id"))).findFirst().orElseThrow(()->new ApiException(400,"未知填报字段"));
            String value=entry.getValue()==null?"":String.valueOf(entry.getValue()).trim();
            if(value.equals(existing.getOrDefault(key,"")))continue;
            if(!"admin".equals(u.get("role"))&&!u.get("role").equals(field.get("dept")))throw new ApiException(403,"无权修改其他部门字段："+field.get("label"));
            if(value.length()>10000)throw new ApiException(400,"字段内容过长");
            if(assistant) {
                if(!(entry.getValue() instanceof String))throw new ApiException(400,"助手填写内容必须为文本");
                var errors=validate(Map.of(key,value));
                for(var error:errors)if(key.equals(error.get("field"))&&!value.isBlank())
                    throw new ApiException(422,error.get("message"));
            }
            putField(id,key,value,u);
            if(assistant&&!value.isBlank())db.update("INSERT IGNORE INTO assistant_reference_fields(project_id,field_key) VALUES(?,?)",id,key);
            else clearAssistantReference(id,key);
            changed.add(String.valueOf(field.get("label")));
        }
        if(!changed.isEmpty()) {
            var f=form(id);
            db.update("UPDATE projects SET name=?,version=?,form_status='draft',form_version=form_version+1,revision=revision+1 WHERE id=?",f.getOrDefault("fullName", "").isBlank()?p.get("name"):f.get("fullName"),f.getOrDefault("version", "").isBlank()?p.get("version"):f.get("version"),id);
            log(id,u,assistant?"助手代填草稿":"保存填报草稿",String.join("、",changed));
        }
        return detail(id,u);
    }
    List<Map<String,String>> validate(Map<String,String> f) {
        var errors=new ArrayList<Map<String,String>>();
        for(var field:fields) {
            String id=String.valueOf(field.get("id")),label=String.valueOf(field.get("label")),value=f.getOrDefault(id,"").trim();
            if(value.isEmpty()) {if(field.containsKey("required"))errors.add(Map.of("field",id,"message",label+"为必填项"));continue;}
            if("number".equals(field.get("type"))&&(!value.matches("\\d+")||value.length()>9))errors.add(Map.of("field",id,"message",label+"应为非负整数"));
            if("select".equals(field.get("type"))&&!((List<?>)field.get("opts")).contains(value))errors.add(Map.of("field",id,"message",label+"选项不合法"));
            if("date".equals(field.get("type")))try {if(LocalDate.parse(value).isAfter(LocalDate.now()))errors.add(Map.of("field",id,"message",label+"不能晚于今天"));}catch(Exception e){errors.add(Map.of("field",id,"message",label+"日期格式不合法"));}
        }
        String function=f.getOrDefault("mainFunction","");int length=function.replaceAll("\\s","").codePointCount(0,function.replaceAll("\\s","").length());
        if(!function.isBlank()&&(length<500||length>1300))errors.add(Map.of("field","mainFunction","message","主要功能应为500至1300字（按项目填报规范，不计空白）"));
        for(String id:List.of("fullName","version"))if(f.getOrDefault(id,"").length()>(id.equals("fullName")?200:80))errors.add(Map.of("field",id,"message","软件名称或版本超出长度限制"));
        return errors;
    }
    @Transactional Map<String,Object> submit(String id,Object revision,Map<String,Object> u) {
        var p=raw(id,u,true);if(!Set.of("draft","returned").contains(String.valueOf(p.get("form_status"))))throw new ApiException(409,"当前状态不能重复提交");
        if(revision!=null)checkRevision(p,revision);
        var errors=validate(form(id));if(!errors.isEmpty())throw new ApiException(422,"填报校验未通过："+errors.get(0).get("message"));
        db.update("UPDATE projects SET form_status='submitted',revision=revision+1 WHERE id=?",id);log(id,u,"提交表单审核","填报版本 v"+p.get("form_version"));return detail(id,u);
    }
    String formStatus(Map<String,Object> project) {
        String status = String.valueOf(project.get("form_status"));
        if (!"approved".equals(status)) return status;
        String id = String.valueOf(project.get("id"));
        var values = form(id);
        return allFieldsApproved(values, reviews(id, values)) ? "approved" : "submitted";
    }

    private boolean allFieldsApproved(Map<String,String> values, Map<String,Object> reviews) {
        return fields.stream()
            .filter(field -> field.containsKey("required") || !values.getOrDefault(String.valueOf(field.get("id")), "").isBlank())
            .allMatch(field -> reviews.get(String.valueOf(field.get("id"))) instanceof Map<?,?> review && "approved".equals(review.get("status")));
    }

    @Transactional Map<String,Object> review(String id,Map<String,Object> body,Map<String,Object> u) {
        var p=raw(id,u,true);auth.requireAdmin(u);
        String previousStatus = formStatus(p);
        if(!Set.of("submitted","returned").contains(previousStatus))throw new ApiException(409,"请先提交表单审核");
        String status=text(body,"status"),key=text(body,"field"),comment=text(body,"comment");
        if(!Set.of("approved","returned").contains(status))throw new ApiException(400,"审核状态不合法");
        if(status.equals("returned")&&comment.isEmpty())throw new ApiException(400,"退回时必须填写原因");
        var f=form(id);
        var selected=fields.stream().filter(x->key.equals("all")||key.equals(x.get("id"))).toList();
        if(selected.isEmpty())throw new ApiException(400,"未知字段");
        if(key.equals("all")&&status.equals("approved")&&!validate(f).isEmpty())throw new ApiException(422,"仍有未通过的填报校验项");
        for(var field:selected) {
            String fieldId=String.valueOf(field.get("id")),value=f.getOrDefault(fieldId,"");
            if(status.equals("approved")&&value.isBlank()) {if(key.equals("all")&&!field.containsKey("required"))continue;throw new ApiException(422,"空字段不能审核通过");}
            db.update("INSERT INTO field_reviews(project_id,field_key,field_value_hash,form_version,status,comment,reviewer_id) VALUES(?,?,?,?,?,?,?)",id,fieldId,AuthService.hash(value),p.get("form_version"),status,comment,u.get("id"));
        }
        var reviews=reviews(id,f);
        boolean all=allFieldsApproved(f,reviews);
        String state=status.equals("returned")?"returned":all?"approved":previousStatus;
        db.update("UPDATE projects SET form_status=?,revision=revision+1 WHERE id=?",state,id);log(id,u,status.equals("returned")?"退回填报字段":"核实填报字段",key+" "+comment);return detail(id,u);
    }
}
