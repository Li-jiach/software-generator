package cn.copyright.workspace;

import java.util.*;
import java.util.function.BiConsumer;
import java.util.function.Supplier;
import org.springframework.stereotype.Service;

@Service
class AssistantActions {
    final ProjectService projects;
    final AssistantBridge ai;
    final AttachmentStore store;
    AssistantActions(ProjectService projects,AssistantBridge ai,AttachmentStore store){this.projects=projects;this.ai=ai;this.store=store;}
    int offset(Map<?,?> args){try{return Math.max(0,Integer.parseInt(String.valueOf(args.getOrDefault("offset",null)==null?0:args.get("offset"))));}catch(Exception e){throw new ApiException(400,"读取位置不合法");}}
    Map<String,Object> attachment(String id){
        var rows=projects.db().queryForList("SELECT a.*,p.name AS project_name FROM attachments a JOIN projects p ON p.id=a.project_id WHERE a.id=? AND a.deleted=FALSE",id);
        if(rows.isEmpty())throw new ApiException(404,"附件不存在");return rows.get(0);
    }
    List<Map<String,Object>> search(Map<?,?> args,String currentId){
        String q=ProjectService.text(args,"query");int offset=offset(args);
        if(q.length()>200)throw new ApiException(400,"附件检索词过长");
        String term=likeTerm(q);
        return projects.db().queryForList("""
            SELECT a.id,a.project_id AS projectId,p.name AS projectName,p.archived,a.name,a.version,a.byte_size AS size
            FROM attachments a JOIN projects p ON p.id=a.project_id
            WHERE a.deleted=FALSE AND (a.name LIKE ? ESCAPE '!' OR p.name LIKE ? ESCAPE '!' OR a.extracted_text LIKE ? ESCAPE '!')
            ORDER BY (a.project_id=?) DESC,a.created_at DESC,a.id LIMIT 20 OFFSET ?
            """,term,term,term,currentId,offset);
    }
    private String likeTerm(String query) {
        return "%"+query.replace("!","!!").replace("%","!%").replace("_","!_")+"%";
    }

    private List<Map<String,Object>> searchProjects(Map<?,?> args, String currentId, Map<String,Object> user) {
        String query=ProjectService.text(args,"query");
        if(query.length()>200)throw new ApiException(400,"项目检索词过长");
        if(query.isBlank()) {
            return projects.db().queryForList("""
                SELECT id,name,version,archived FROM projects WHERE id=?
                """,currentId);
        }
        String term=likeTerm(query);
        return projects.db().queryForList("""
            SELECT p.id,p.name,p.version,p.archived
            FROM projects p
            WHERE p.id=? OR p.name LIKE ? ESCAPE '!'
                OR ((? OR JSON_CONTAINS(p.allowed_roles,JSON_QUOTE(?)))
                    AND (p.description LIKE ? ESCAPE '!'
                        OR EXISTS(SELECT 1 FROM project_fields f WHERE f.project_id=p.id
                            AND f.field_key IN ('fullName','shortName') AND f.field_value LIKE ? ESCAPE '!')))
                OR EXISTS(SELECT 1 FROM attachments a WHERE a.project_id=p.id AND a.deleted=FALSE
                    AND (a.name LIKE ? ESCAPE '!' OR a.extracted_text LIKE ? ESCAPE '!'))
            ORDER BY (p.id=? OR p.name=?) DESC,(p.name LIKE ? ESCAPE '!') DESC,p.archived,p.updated_at DESC,p.id
            LIMIT 20
            """,query,term,"admin".equals(user.get("role")),user.get("role"),term,term,term,term,query,query,term);
    }

    private Map<String,Object> projectRag(String id,String query,String question,Map<String,Object> user,
                                          List<Map<String,Object>> history) {
        var found=projects.db().queryForList("SELECT * FROM projects WHERE id=?",id);
        if(found.isEmpty())throw new ApiException(404,"未找到对应软著项目");
        var p=found.get(0);
        var basic=new LinkedHashMap<String,Object>();
        basic.put("项目编号",id);
        basic.put("项目名称",p.get("name"));
        basic.put("项目版本",p.get("version"));
        basic.put("已归档",p.get("archived"));
        if(projects.canView(p,user)) {
            basic.put("承担部门",p.get("department"));
            basic.put("负责人",p.get("owner"));
            basic.put("项目说明",p.get("description"));
            basic.put("填报状态",Map.of("draft","填写中","submitted","等待管理员核实","returned","已退回修改","approved","已核实")
                .get(String.valueOf(p.get("form_status"))));
            var manuals=projects.db().queryForList("SELECT status,comment FROM project_manuals WHERE project_id=?",id);
            basic.put("操作手册",manuals.isEmpty()?"尚未编写":manuals.get(0));
            var records=projects.db().queryForList("""
                SELECT status,reference_no AS referenceNo,occurred_at AS occurredAt,note
                FROM application_records WHERE project_id=? ORDER BY occurred_at DESC,created_at DESC LIMIT 1
                """,id);
            basic.put("最新办理记录",records.isEmpty()?"尚无记录":records.get(0));
            var values=projects.form(id);
            for(var field:projects.fields()) {
                String value=values.getOrDefault(String.valueOf(field.get("id")),"");
                if(!value.isBlank())basic.put(String.valueOf(field.get("label")),value);
            }
        }
        String title=p.get("name")+" "+p.get("version");
        String info=projects.encode(basic);
        var sources=new ArrayList<Map<String,Object>>();
        sources.add(Map.of("id","form:"+id,"name",title+" 基础信息","text",info,"project_id",id));
        // Prioritize filename and text matches before imposing the per-request size limit.
        String term=likeTerm(query);
        var files=projects.db().queryForList("""
            SELECT id, name, version, extracted_text, extraction_warning
            FROM attachments WHERE project_id=? AND deleted=FALSE
            ORDER BY (name LIKE ? ESCAPE '!') DESC,(extracted_text LIKE ? ESCAPE '!') DESC,
                created_at DESC,version DESC,id LIMIT 90
            """,id,term,term);
        int budget=3_000_000;
        for(var file:files) {
            String text=ProjectService.text(file,"extracted_text");
            String metadata="附件："+file.get("name")+"，版本："+file.get("version")+"。 "+file.get("extraction_warning");
            if(text.length()+metadata.length()>budget)continue;
            budget-=text.length()+metadata.length();
            sources.add(Map.of("id",file.get("id"),"name",file.get("name")+" · v"+file.get("version"),
                "text",metadata+"\n\n"+text.substring(0,Math.min(text.length(),300000-metadata.length()-2)),"project_id",id));
        }
        return Map.of("question",question,"query",query,"sources",sources,"history",history,
            "include_knowledge",false,"project_context",info.substring(0,Math.min(12000,info.length())));
    }

    record Result(Map<String,Object> response,String query,Supplier<Map<String,Object>> mutation) {
        Result(Map<String,Object> response,String query){this(response,query,null);}
    }
    Result run(String id,String question,String page,String scope,Map<String,Object> user,List<Map<String,Object>> history,List<Map<String,Object>> memory,boolean hasUnsaved,
               List<Map<String,Object>> operations,BiConsumer<String,Map<String,Object>> events){
        var context=new LinkedHashMap<String,Object>();context.put("page",page);context.put("projectId",id);context.put("scope",scope);
        context.put("recentOperations",memory);
        context.put("fields",projects.fields().stream().filter(f->"admin".equals(user.get("role"))||user.get("role").equals(f.get("dept"))).toList());
        Integer revision=null;
        if(!id.isBlank()){
            var p=projects.raw(id,user,false);
            revision=((Number)p.get("revision")).intValue();
            context.put("form",projects.form(id));
            context.put("name",p.get("name"));
            context.put("version",p.get("version"));
            context.put("recentProjectActivity",projects.db().queryForList("""
                SELECT a.title,LEFT(a.detail,300) AS detail,a.created_at AS time,u.display_name AS actor
                FROM activity_logs a JOIN users u ON u.id=a.actor_id
                WHERE a.project_id=? ORDER BY a.id DESC LIMIT 8
                """,id));
            context.put("recentAttachments",projects.db().queryForList("""
                SELECT id,name,category,version,extraction_warning AS warning
                FROM attachments WHERE project_id=? AND deleted=FALSE ORDER BY created_at DESC,version DESC LIMIT 12
                """,id));
        }
        var observations=new ArrayList<Map<String,Object>>();var sources=new ArrayList<Map<String,Object>>();
        var candidates=new HashMap<String,Map<String,Object>>();
        var reads=new HashSet<List<Object>>();
        for(int step=0;step<8;step++){
            context.put("remainingLookupSteps",7-step);
            var plan=ai.request("POST","/agent/step",Map.of("question",question,"context",context,"observations",observations,"history",history));
            String action=ProjectService.text(plan,"action");Map<?,?> args=plan.get("args") instanceof Map<?,?> m?m:Map.of();
            if(Set.of("search_projects","search_attachments","read_attachment").contains(action)){
                if(step==7)break;
                var key=List.<Object>of(action,ProjectService.text(args,"id"),ProjectService.text(args,"entry"),
                    ProjectService.text(args,"query").toLowerCase(Locale.ROOT),offset(args));
                if(!reads.add(key)){
                    observations.add(Map.of("action",action,"result","已返回相同条件的结果，请使用已有证据或换用不同资料。"));
                    continue;
                }
            }
            boolean tracked=events!=null&&Set.of("search_projects","project_rag","status","search_attachments","read_attachment").contains(action);
            if(tracked)events.accept("tool",Map.of("name",action,"state","running"));
            boolean success=false;
            try {
                var result=executePlan(action,id,page,args,question,user,history,hasUnsaved,revision,observations,sources,candidates,operations,events,plan);
                success=true;
                if(result!=null)return result;
            } finally {
                if(tracked)events.accept("tool",Map.of("name",action,"state",success?"finished":"failed"));
            }
        }
        return result(sources.isEmpty()
            ?"本轮没有找到可用于回答或填报的资料。若已上传操作手册，请确认附件有可复制的文本。"
            :"本轮已找到参考资料，但未整理出可核实的结果。下方列出已读取的来源。",sources);
    }
    private Result executePlan(String action,String id,String page,Map<?,?> args,String question,
                               Map<String,Object> user,List<Map<String,Object>> history,boolean hasUnsaved,Integer revision,
                               List<Map<String,Object>> observations,List<Map<String,Object>> sources,
                               Map<String,Map<String,Object>> candidates,List<Map<String,Object>> operations,BiConsumer<String,Map<String,Object>> events,Map<String,Object> plan){
        switch(action){
                case "knowledge":
                    String query=ProjectService.required(args,"query",500);
                    operations.add(Map.of("action",action,"query",query));
                    return new Result(null,query);
                case "search_projects":
                    var matches=searchProjects(args,id,user);
                    for(var match:matches)candidates.put(String.valueOf(match.get("id")),match);
                    operations.add(Map.of("action",action,"query",ProjectService.text(args,"query"),"count",matches.size()));
                    observations.add(Map.of("action",action,"result",matches));break;
                case "project_rag":
                    String selected=ProjectService.required(args,"projectId",40);
                    if(!candidates.containsKey(selected))throw new ApiException(422,"请先定位要检索的软著项目");
                    var match=candidates.get(selected);
                    var answer=ai.answer(projectRag(selected,ProjectService.required(args,"query",500),question,user,history),events);
                    operations.add(Map.of("action",action,"projectId",selected,"projectName",match.get("name"),"version",match.get("version")));
                    return new Result(answer,null);
                case "status":
                    if(id.isBlank())return result("请先选择要查询的项目。",sources);
                    var detail=projects.detail(id,user);
                    String state=Map.of("draft","填写中","submitted","等待管理员核实","returned","已退回修改","approved","已核实").get(String.valueOf(detail.get("formStatus")));
                    var manuals=projects.db().queryForList("SELECT status,comment FROM project_manuals WHERE project_id=?",id);
                    StringBuilder statusText=new StringBuilder("项目："+detail.get("name")+"\n填报状态："+state+"\n");
                    var errors=(List<?>)detail.get("validation");statusText.append("待完善字段：").append(errors.size()).append("项\n");for(var error:errors)statusText.append("• ").append(((Map<?,?>)error).get("message")).append('\n');
                    statusText.append("手册状态：").append(manuals.isEmpty()?"尚未编写":Map.of("draft","编写中","submitted","待管理员审核","returned","已退回","approved","已核实").get(String.valueOf(manuals.get(0).get("status")))+" "+manuals.get(0).get("comment"));
                    var records=(List<?>)detail.get("records");
                    statusText.append("\n最新办理记录：");
                    if(records.isEmpty())statusText.append("尚无记录");
                    else {
                        var record=(Map<?,?>)records.get(0);
                        statusText.append(record.get("status")).append(" · ").append(record.get("occurredAt"));
                        if(!ProjectService.text(record,"referenceNo").isBlank())statusText.append(" · ").append(record.get("referenceNo"));
                    }
                    operations.add(Map.of("action",action,"projectId",id,"projectName",detail.get("name"),"version",detail.get("version")));
                    return result(statusText.toString(),sources);
                case "fill_form":
                    if(!"basic".equals(page))return result("请打开该项目的「基础信息填报」页面，再请我填写。",sources);
                    if(hasUnsaved)return result("页面有尚未保存的修改，请先保存草稿，再让我代填，避免覆盖你的输入。",sources);
                    if(id.isBlank())return result("请先选择需要填写的项目。",sources);
                    if(!question.matches("(?s).*(代填|填写(?:(?:软著)?基础信息|表单|当前页面|当前表单)|帮我.{0,80}(填|写入|改|设置|补充|完善|更新|录入)|请.{0,80}(填|写入|改|设置|补充|完善|更新|录入)|(?:把|将).{1,80}(填为|改为|设为|写入|改成|填成|换成|更新为)|(?:填入|填写为|改为|设置为|改成|填成|换成|更新为).+).*"))return result("请明确需要填写或更新的字段。",sources);
                    if(!(args.get("fields") instanceof Map<?,?> values)||values.isEmpty())return result("尚未找到可填写的字段，请补充资料。",sources);
                    if(!id.equals(ProjectService.text(args,"projectId")))
                        return result("请切换到要修改的软著项目，再打开「基础信息填报」确认修改。",sources);
                    return new Result(null,null,()->{
                        var saved=projects.saveAssistantForm(id,Map.of("revision",revision,"fields",values),user);
                        @SuppressWarnings("unchecked")
                        var changes=(List<Map<String,String>>)saved.remove("assistantChanges");
                        operations.add(Map.of("action",action,"projectId",id,"projectName",saved.get("name"),
                            "version",saved.get("version"),"changes",changes));
                        var labels=changes.stream().map(change->change.get("label")).toList();
                        String text=labels.isEmpty()?"该项目草稿没有发生修改。"
                            :"已修改「"+saved.get("name")+"」草稿中的"+String.join("、",labels)
                                +"。AI 辅助填写仅供参考，请核对实际资料并人工修订，切勿直接用于申报。";
                        var result=answer(text,sources);
                        result.put("changed",!changes.isEmpty());
                        result.put("project",saved);
                        if(args.get("missing") instanceof String missing&&!missing.isBlank())
                            result.put("answer",text+"\n仍需补充："+missing.substring(0,Math.min(1000,missing.length())));
                        return result;
                    });
                case "search_attachments":
                    var files=search(args,id);
                    operations.add(Map.of("action",action,"query",ProjectService.text(args,"query"),"count",files.size()));
                    observations.add(Map.of("action",action,"result",files));break;
                case "read_attachment":
                    var file=attachment(ProjectService.text(args,"id"));Object content;
                    try{content=read(file,args);}
                    catch(ApiException e){observations.add(Map.of("action",action,"name",file.get("name"),"result",Map.of("warning",e.getMessage())));break;}
                    observations.add(Map.of("action",action,"name",file.get("name"),"projectName",file.get("project_name"),"version",file.get("version"),"result",content));
                    operations.add(Map.of("action",action,"attachment",file.get("name"),"sourceProject",file.get("project_name"),
                        "attachmentVersion",file.get("version"),"entry",ProjectService.text(args,"entry")));
                    String excerpt=projects.encode(content);sources.add(Map.of("id",file.get("id"),"name",file.get("name"),"project_id",file.get("project_id"),"excerpt",excerpt.substring(0,Math.min(excerpt.length(),16000))));break;
                case "answer":return result(ProjectService.required(plan,"answer",50000),sources);
                default:throw new ApiException(502,"模型未返回有效的行动计划");
        }
        return null;
    }
    Object read(Map<String,Object> file,Map<?,?> args){
        int offset=offset(args);
        if(ProjectService.text(file,"name").toLowerCase(Locale.ROOT).endsWith(".zip"))return store.zipEntry(file,ProjectService.text(args,"entry"),offset);
        String text=ProjectService.text(file,"extracted_text"),warning=ProjectService.text(file,"extraction_warning");
        if(text.isBlank()){
            var extracted=store.extract(file);
            text=ProjectService.text(extracted,"text");warning=ProjectService.text(extracted,"warning");
        }
        String query=ProjectService.text(args,"query");
        if(!query.isBlank()&&!text.isBlank()){
            var focused=ai.request("POST","/retrieve",Map.of("query",query,"sources",List.of(Map.of(
                "id",file.get("id"),"name",file.get("name"),"text",text))));
            if(focused.get("excerpts") instanceof List<?> hits&&!hits.isEmpty())return Map.of("excerpts",hits,"warning",warning);
        }
        int start=Math.min(offset,text.length()),end=Math.min(start+16000,text.length());
        return Map.of("text",text.substring(start,end),"nextOffset",end,"total",text.length(),"warning",warning);
    }
    Map<String,Object> answer(String answer,List<Map<String,Object>> sources){var result=new LinkedHashMap<String,Object>();result.put("answer",answer);result.put("sources",sources);result.put("mode","action");return result;}
    Result result(String text,List<Map<String,Object>> sources){return new Result(answer(text,sources),null);}
}
