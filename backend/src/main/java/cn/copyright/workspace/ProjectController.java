package cn.copyright.workspace;

import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.*;
import org.springframework.http.*;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api")
class ProjectController {
    final ProjectService projects; final AuthService auth; final AssistantBridge ai; final AttachmentStore store;
    ProjectController(ProjectService projects,AuthService auth,AssistantBridge ai,AttachmentStore store){this.projects=projects;this.auth=auth;this.ai=ai;this.store=store;}
    @GetMapping("/metadata") Map<String,Object> metadata(HttpServletRequest req){auth.current(req);return Map.of("fields",projects.fields(),"deferred",List.of("rpa"));}
    @GetMapping("/projects") Object list(HttpServletRequest req){return projects.list(auth.current(req));}
    @PostMapping("/projects") Object create(@RequestBody Map<String,Object> b,HttpServletRequest req){return projects.create(b,auth.current(req));}
    @GetMapping("/projects/{id}") Object detail(@PathVariable String id,HttpServletRequest req){return projects.detail(id,auth.current(req));}
    @PutMapping("/projects/{id}") Object update(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req){return projects.update(id,b,auth.current(req));}
    @DeleteMapping("/projects/{id}") Object archive(@PathVariable String id,HttpServletRequest req){projects.archive(id,auth.current(req));return Map.of("ok",true);}
    @PutMapping("/projects/{id}/form") Object form(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req){return projects.saveForm(id,b,auth.current(req));}
    @PostMapping("/projects/{id}/form/validate") Object validate(@PathVariable String id,HttpServletRequest req){projects.raw(id,auth.current(req),false);return projects.validate(projects.form(id));}
    @PostMapping("/projects/{id}/form/submit") Object submit(@PathVariable String id,@RequestBody(required=false) Map<String,Object> b,HttpServletRequest req){return projects.submit(id,b==null?null:b.get("revision"),auth.current(req));}
    @PostMapping("/projects/{id}/form/review") Object review(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req){return projects.review(id,b,auth.current(req));}

    @PostMapping("/projects/{id}/files")
    @Transactional
    Object upload(@PathVariable String id,@RequestParam MultipartFile file,@RequestParam(defaultValue="其他附件") String category,HttpServletRequest req) throws Exception {
        var user=auth.current(req);projects.raw(id,user,true);
        boolean zip=Objects.requireNonNullElse(file.getOriginalFilename(),"").toLowerCase(Locale.ROOT).endsWith(".zip");
        if(file.isEmpty()||(!zip && file.getSize()>20*1024*1024))throw new ApiException(400,"请上传非空文件，非ZIP文件上限20MB");
        if(category.length()>80)throw new ApiException(400,"附件分类过长");
        String name=Objects.requireNonNullElse(file.getOriginalFilename(),"附件").replaceAll("[\\\\/]","_").replaceAll("[\r\n\u0000]","");
        if(name.isBlank()||name.length()>255)throw new ApiException(400,"文件名不合法");
        String fid=UUID.randomUUID().toString();
        int version=projects.db().queryForObject("SELECT COALESCE(MAX(version),0)+1 FROM attachments WHERE project_id=? AND name=?",Integer.class,id,name);
        var stored=store.store(fid,file);
        org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(new org.springframework.transaction.support.TransactionSynchronization() {
            public void afterCompletion(int status) {
                if(status!=STATUS_COMMITTED) try {java.nio.file.Files.deleteIfExists(java.nio.file.Path.of(String.valueOf(stored.get("path"))));}catch(Exception ignored){}
            }
        });
        var extracted=store.extract(Map.of("name",name,"storage_path",stored.get("path")));
        String contentType=zip?"application/zip":Objects.requireNonNullElse(file.getContentType(),"application/octet-stream");
        projects.db().update("INSERT INTO attachments(id,project_id,name,category,content_type,byte_size,version,content_sha256,storage_path,extracted_text,extraction_warning,uploaded_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",fid,id,name,category,contentType,file.getSize(),version,stored.get("sha"),stored.get("path"),extracted.getOrDefault("text",""),extracted.getOrDefault("warning",""),user.get("id"));
        projects.bump(id);projects.log(id,user,"上传附件",name+" v"+version);return Map.of("id",fid,"version",version,"warning",extracted.getOrDefault("warning",""));
    }
    Map<String,Object> file(String id,String fileId,Map<String,Object> user,boolean content) {
        projects.raw(id,user,false);
        var rows=projects.db().queryForList("SELECT "+(content?"*":"id,name,extracted_text,extraction_warning")+" FROM attachments WHERE id=? AND project_id=? AND deleted=FALSE",fileId,id);
        if(rows.isEmpty())throw new ApiException(404,"附件不存在");return rows.get(0);
    }
    @GetMapping("/projects/{id}/files/{fileId}/text") Object fileText(@PathVariable String id,@PathVariable String fileId,HttpServletRequest req){var f=file(id,fileId,auth.current(req),false);return Map.of("name",f.get("name"),"text",f.get("extracted_text"),"warning",f.get("extraction_warning"));}
    @GetMapping("/projects/{id}/files/{fileId}/download") ResponseEntity<org.springframework.core.io.Resource> download(@PathVariable String id,@PathVariable String fileId,@RequestParam(defaultValue="false") boolean inline,HttpServletRequest req) {
        var f=file(id,fileId,auth.current(req),true);String type=String.valueOf(f.get("content_type"));
        boolean safeInline=inline&&(type.equals("application/pdf")||Set.of("image/png","image/jpeg","image/webp","image/gif").contains(type));
        var disposition=(safeInline?ContentDisposition.inline():ContentDisposition.attachment()).filename(String.valueOf(f.get("name")),StandardCharsets.UTF_8).build();
        return ResponseEntity.ok().contentType(MediaType.parseMediaType(safeInline?type:"application/octet-stream")).header(HttpHeaders.CONTENT_DISPOSITION,disposition.toString()).header("Content-Security-Policy","sandbox").body(store.resource(f));
    }
    @DeleteMapping("/projects/{id}/files/{fileId}") @Transactional Object removeFile(@PathVariable String id,@PathVariable String fileId,HttpServletRequest req){
        var u=auth.current(req);projects.raw(id,u,true);var f=file(id,fileId,u,false);
        boolean manualFile=Boolean.TRUE.equals(projects.db().queryForObject("""
            SELECT EXISTS(SELECT 1 FROM project_manuals WHERE attachment_id=?) OR
                   EXISTS(SELECT 1 FROM manual_reviews WHERE attachment_id=?)
            """,Boolean.class,fileId,fileId));
        if(manualFile)throw new ApiException(409,"附件已用于操作手册审核，需保留审核原件");
        projects.db().update("UPDATE attachments SET deleted=TRUE WHERE id=?",fileId);projects.bump(id);
        projects.log(id,u,"移除附件",String.valueOf(f.get("name")));return Map.of("ok",true);
    }
    @PostMapping("/projects/{id}/files/{fileId}/extract") Object reextract(@PathVariable String id,@PathVariable String fileId,HttpServletRequest req){var u=auth.current(req);var f=file(id,fileId,u,true);var result=store.extract(f);projects.db().update("UPDATE attachments SET extracted_text=?,extraction_warning=? WHERE id=?",result.get("text"),result.get("warning"),fileId);return result;}
    @PutMapping("/projects/{id}/files/{fileId}") @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    Object categorize(@PathVariable String id,@PathVariable String fileId,@RequestBody Map<String,Object> b,HttpServletRequest req){
        var user=auth.current(req);projects.raw(id,user,true);file(id,fileId,user,false);
        String type=ProjectService.required(b,"type",80);
        int changed=projects.db().update("UPDATE attachments SET category=? WHERE id=? AND category<>?",type,fileId,type);
        if(changed>0){
            projects.db().update("UPDATE application_material_reviews SET invalidated=TRUE WHERE attachment_id=?",fileId);
            projects.bump(id);projects.log(id,user,"调整附件分类",fileId+"："+type);
        }
        return Map.of("ok",true);
    }
    @PostMapping("/projects/{id}/records") @Transactional Object addRecord(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req) {
        return saveRecord(id,null,b,req);
    }
    @PutMapping("/projects/{id}/records/{recordId}") @Transactional Object editRecord(@PathVariable String id,@PathVariable String recordId,@RequestBody Map<String,Object> b,HttpServletRequest req) {
        return saveRecord(id,recordId,b,req);
    }
    @DeleteMapping("/projects/{id}/records/{recordId}") @Transactional Object deleteRecord(@PathVariable String id,@PathVariable String recordId,HttpServletRequest req) {
        var u=auth.current(req); projects.raw(id,u,true);
        if(!Set.of("admin","adminDept").contains(u.get("role")))throw new ApiException(403,"无权修改申报记录");
        if(projects.db().update("DELETE FROM application_records WHERE project_id=? AND id=?",id,recordId)==0)throw new ApiException(404,"记录不存在");
        projects.bump(id);projects.log(id,u,"删除申报记录",recordId);return projects.detail(id,u);
    }
    Object saveRecord(String id,String recordId,Map<String,Object> b,HttpServletRequest req) {
        var u=auth.current(req);projects.raw(id,u,true);if(!Set.of("admin","adminDept").contains(u.get("role")))throw new ApiException(403,"仅管理员或行政业务办可登记申报记录");
        String status=ProjectService.required(b,"status",30);if(!Set.of("待申报","已提交","已受理","待补正","审核中","登记完成","已撤回","未通过").contains(status))throw new ApiException(400,"申报状态不合法");
        String reference=ProjectService.text(b,"referenceNo"),note=ProjectService.required(b,"note",5000),evidence=ProjectService.text(b,"evidenceId");
        if(reference.length()>100)throw new ApiException(400,"受理或登记编号过长");
        if(Set.of("已受理","登记完成").contains(status)&&reference.isBlank())throw new ApiException(400,"请填写真实受理号或登记号");
        if(!evidence.isEmpty())file(id,evidence,u,false);
        LocalDateTime time;try{time=LocalDateTime.parse(ProjectService.required(b,"occurredAt",40));}catch(Exception e){throw new ApiException(400,"请填写有效办理时间");}
        if(time.isAfter(LocalDateTime.now().plusMinutes(5)))throw new ApiException(400,"办理时间不能在未来");
        if(recordId==null) {
            projects.db().update("INSERT INTO application_records(id,project_id,status,reference_no,occurred_at,note,evidence_id,created_by) VALUES(?,?,?,?,?,?,?,?)",UUID.randomUUID().toString(),id,status,reference,time,note,evidence.isBlank()?null:evidence,u.get("id"));
        } else if(projects.db().update("UPDATE application_records SET status=?,reference_no=?,occurred_at=?,note=?,evidence_id=? WHERE id=? AND project_id=?",status,reference,time,note,evidence.isBlank()?null:evidence,recordId,id)==0)throw new ApiException(404,"记录不存在");
        projects.bump(id);projects.log(id,u,recordId==null?"登记申报记录":"编辑申报记录",status+" "+reference);return projects.detail(id,u);
    }
    @GetMapping("/projects/{id}/reuse/{sourceId}") Object reuse(@PathVariable String id,@PathVariable String sourceId,HttpServletRequest req){var u=auth.current(req);projects.raw(id,u,false);projects.raw(sourceId,u,false);return Map.of("sourceId",sourceId,"fields",projects.form(sourceId));}
    @GetMapping("/notifications") Object notifications(HttpServletRequest req){
        var u=auth.current(req);var result=new ArrayList<Map<String,Object>>();
        boolean admin="admin".equals(u.get("role"));
        String taskStatus=admin?"submitted":"returned";
        for(var p:projects.list(u)) {
            String status=String.valueOf(p.get("formStatus"));
            if(taskStatus.equals(status)) result.add(Map.of("projectId",p.get("id"),"name",p.get("name")+" · 人工填报全部核实","status",status,"kind","form"));
            for(var m:projects.db().queryForList("SELECT status FROM project_manuals WHERE project_id=? AND status=?",p.get("id"),taskStatus))
                result.add(Map.of("projectId",p.get("id"),"name",p.get("name")+" · 操作手册已核实","status",m.get("status"),"kind","manual"));
            for(String kind : ProjectService.APPLICATION_MATERIALS) {
                var material=projects.materialReview(String.valueOf(p.get("id")),kind);
                if(taskStatus.equals(material.get("status")))
                    result.add(Map.of("projectId",p.get("id"),"name",p.get("name")+" · "+material.get("label"),"status",taskStatus,"kind",kind));
            }
        }
        return result;
    }
}
