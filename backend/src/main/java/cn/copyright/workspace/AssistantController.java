package cn.copyright.workspace;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.function.BiConsumer;
import java.util.*;
import com.fasterxml.jackson.core.type.TypeReference;
import org.springframework.web.bind.annotation.*;
import org.springframework.transaction.support.TransactionTemplate;

@RestController
@RequestMapping("/api/assistant")
class AssistantController {
    final AuthService auth;final ProjectService projects;final AssistantBridge ai;final AssistantActions actions;
    final TransactionTemplate transactions;
    AssistantController(AuthService auth,ProjectService projects,AssistantBridge ai,AssistantActions actions,TransactionTemplate transactions){
        this.auth=auth;this.projects=projects;this.ai=ai;this.actions=actions;this.transactions=transactions;
    }
    String checkScope(String scope){if(!Set.of("knowledge","project","history").contains(scope))throw new ApiException(400,"问答范围不合法");return scope;}
    void checkProject(String id,Map<String,Object> user){if(!id.isBlank())projects.raw(id,user,false);}
    @GetMapping("/config") Object config(HttpServletRequest r){auth.requireAdmin(auth.current(r));return ai.request("GET","/config",null);}
    @PutMapping("/config") Object config(@RequestBody Map<String,Object> body,HttpServletRequest r){auth.requireAdmin(auth.current(r));return ai.request("PUT","/config",body);}
    @PostMapping("/config/test") Object test(HttpServletRequest r){auth.requireAdmin(auth.current(r));return ai.request("POST","/config/test",Map.of());}
    List<Map<String,Object>> history(String id,String scope,Map<String,Object> user,int limit){
        checkScope(scope);checkProject(id,user);
        var rows=projects.db().queryForList("SELECT id,role,content,sources_json,operations_json,mode,created_at AS time FROM chat_messages WHERE user_id=? AND COALESCE(project_id,'')=? AND scope=? AND cleared=FALSE ORDER BY id DESC LIMIT ?",user.get("id"),id,scope,limit);
        Collections.reverse(rows);
        for(var row:rows){
            row.put("sources",projects.decode(row.remove("sources_json"),new TypeReference<List<Map<String,Object>>>(){}));
            var operations=row.remove("operations_json");
            row.put("operations",operations==null?List.of():projects.decode(operations,new TypeReference<List<Map<String,Object>>>(){}));
        }
        return rows;
    }
    @GetMapping("/messages") Object messages(@RequestParam(defaultValue="") String projectId,@RequestParam(defaultValue="knowledge") String scope,HttpServletRequest r){return history(projectId,scope,auth.current(r),100);}
    @DeleteMapping("/messages") Object clear(@RequestParam(defaultValue="") String projectId,@RequestParam(defaultValue="knowledge") String scope,HttpServletRequest r){var u=auth.current(r);checkScope(scope);checkProject(projectId,u);projects.db().update("UPDATE chat_messages SET cleared=TRUE WHERE user_id=? AND COALESCE(project_id,'')=? AND scope=?",u.get("id"),projectId,scope);return Map.of("ok",true);}
    private record ChatInput(Map<String,Object> user,String projectId,String scope,String question,String page,boolean hasUnsaved) {}

    private ChatInput input(Map<String,Object> b,HttpServletRequest req) {
        var user=auth.current(req);
        String id=ProjectService.text(b,"projectId"),scope=checkScope(String.valueOf(b.getOrDefault("scope","knowledge")));
        checkProject(id,user);
        if(!scope.equals("knowledge")&&id.isBlank())throw new ApiException(400,"请先选择项目");
        return new ChatInput(user,id,scope,ProjectService.required(b,"question",4000),ProjectService.text(b,"page"),
            Boolean.TRUE.equals(b.get("hasUnsaved")));
    }

    @PostMapping("/chat") Object chat(@RequestBody Map<String,Object> body,HttpServletRequest req){
        return runChat(input(body,req),null);
    }

    @PostMapping("/chat/stream")
    void stream(@RequestBody Map<String,Object> body,HttpServletRequest req,HttpServletResponse response) throws IOException {
        var input=input(body,req);
        response.setContentType("application/x-ndjson");
        response.setCharacterEncoding("UTF-8");
        response.setHeader("Cache-Control","no-store, no-transform");
        response.setHeader("X-Accel-Buffering","no");
        var out=response.getOutputStream();
        BiConsumer<String,Map<String,Object>> send=(type,data)->{
            var event=new LinkedHashMap<>(data);
            event.put("type",type);
            try {
                out.write((projects.encode(event)+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
                out.flush();
            }catch(IOException e){throw new UncheckedIOException(e);}
        };
        try {
            send.accept("phase",Map.of("name","planning"));
            send.accept("done",runChat(input,send));
        }catch(UncheckedIOException disconnected){
            // The client closed the stream.
        }catch(ApiException e){
            send.accept("error",Map.of("message",e.getMessage()));
        }catch(Exception e){
            send.accept("error",Map.of("message","助手处理失败，请重试"));
        }
    }

    private Map<String,Object> runChat(ChatInput input,BiConsumer<String,Map<String,Object>> events){
        String id=input.projectId(),scope=input.scope(),question=input.question();
        var user=input.user();
        var rows=history(id,scope,user,12);
        var recent=rows.stream().map(m->Map.<String,Object>of("role",m.get("role"),"content",
            clip(String.valueOf(m.get("content")),10000))).toList();
        var memory=recentOperations(rows);
        var operations=new ArrayList<Map<String,Object>>();
        var action=actions.run(id,question,input.page(),scope,user,recent,memory,input.hasUnsaved(),operations,events);
        boolean writing=action.mutation()!=null;
        if(writing&&events!=null)events.accept("tool",Map.of("name","fill_form","state","running"));
        boolean saved=false;
        try {
            var prepared=writing?null:action.response()==null?knowledgeAnswer(question,action.query(),recent,events):action.response();
            var response=Objects.requireNonNull(transactions.execute(status->{
                var result=writing?action.mutation().get():prepared;
                result.put("operations",operations);
                persist(input,result);
                return result;
            }));
            saved=true;
            if(events!=null&&!"model".equals(response.get("mode")))events.accept("delta",Map.of("text",response.get("answer")));
            return response;
        } finally {
            if(writing&&events!=null)events.accept("tool",Map.of("name","fill_form","state",saved?"finished":"failed"));
        }
    }

    private List<Map<String,Object>> recentOperations(List<Map<String,Object>> rows){
        var memory=new ArrayList<Map<String,Object>>();
        for(var row:rows){
            var previous=(List<?>)row.get("operations");
            for(var entry:previous){
                var operation=new LinkedHashMap<String,Object>();
                ((Map<?,?>)entry).forEach((key,value)->operation.put(String.valueOf(key),value));
                operation.put("time",row.get("time"));
                if(operation.get("changes") instanceof List<?> changes){
                    operation.put("changes",changes.stream().map(change->{
                        var values=(Map<?,?>)change;
                        return Map.of("field",values.get("field"),"label",values.get("label"),
                            "before",clip(String.valueOf(values.get("before")),250),
                            "after",clip(String.valueOf(values.get("after")),250));
                    }).toList());
                }
                memory.add(operation);
            }
        }
        int remaining=24000;
        int start=memory.size();
        while(start>0){
            remaining-=projects.encode(memory.get(start-1)).length();
            if(remaining<0)break;
            start--;
        }
        return memory.subList(start,memory.size());
    }

    private static String clip(String value,int max){
        return value.length()<=max?value:value.substring(0,max-1)+"…";
    }

    private Map<String,Object> knowledgeAnswer(String question,String query,List<Map<String,Object>> recent,
                                                BiConsumer<String,Map<String,Object>> events){
        if(events!=null)events.accept("tool",Map.of("name","knowledge","state","running"));
        boolean success=false;
        try {
            var sources=new ArrayList<Map<String,Object>>();
            for(var k:projects.db().queryForList("SELECT id,title,source_url,content FROM knowledge_documents WHERE enabled=TRUE ORDER BY updated_at DESC LIMIT 50"))
                sources.add(Map.of("id","dbkb:"+k.get("id"),"name",k.get("title"),"url",k.get("source_url"),"text",k.get("content")));
            var result=ai.answer(Map.of("question",question,"query",query,"sources",sources,"history",recent),events);
            success=true;
            return result;
        } finally {
            if(events!=null)events.accept("tool",Map.of("name","knowledge","state",success?"finished":"failed"));
        }
    }
    private void persist(ChatInput input,Map<String,Object> response){
        var citations=response.getOrDefault("sources",List.of());
        var operations=response.getOrDefault("operations",List.of());
        projects.db().update("""
            INSERT INTO chat_messages(user_id,project_id,scope,role,content,sources_json,operations_json,mode)
            VALUES (?,?,?,'user',?,'[]',NULL,?), (?,?,?,'assistant',?,?,?,?)
            """,
            input.user().get("id"),input.projectId().isBlank()?null:input.projectId(),input.scope(),input.question(),response.get("mode"),
            input.user().get("id"),input.projectId().isBlank()?null:input.projectId(),input.scope(),response.get("answer"),
            projects.encode(citations),projects.encode(operations),response.get("mode"));
    }
    @GetMapping("/knowledge") Object knowledge(HttpServletRequest req){auth.current(req);return projects.db().queryForList("SELECT id,title,source_url AS sourceUrl,content,version,enabled,updated_at AS updatedAt FROM knowledge_documents ORDER BY updated_at DESC");}
    @PostMapping("/knowledge") Object addKnowledge(@RequestBody Map<String,Object> b,HttpServletRequest req){var u=auth.current(req);auth.requireAdmin(u);String title=ProjectService.required(b,"title",200),content=ProjectService.required(b,"content",100000),url=ProjectService.text(b,"sourceUrl");if(url.length()>1000)throw new ApiException(400,"来源地址过长");String id=UUID.randomUUID().toString();projects.db().update("INSERT INTO knowledge_documents(id,title,source_url,content,updated_by) VALUES(?,?,?,?,?)",id,title,url,content,u.get("id"));return Map.of("id",id);}
    @PutMapping("/knowledge/{id}") Object updateKnowledge(@PathVariable String id,@RequestBody Map<String,Object> b,HttpServletRequest req){var u=auth.current(req);auth.requireAdmin(u);String title=ProjectService.required(b,"title",200),content=ProjectService.required(b,"content",100000),url=ProjectService.text(b,"sourceUrl");if(url.length()>1000)throw new ApiException(400,"来源地址过长");int changed=projects.db().update("UPDATE knowledge_documents SET title=?,source_url=?,content=?,enabled=?,version=version+1,updated_by=? WHERE id=? AND version=?",title,url,content,!Boolean.FALSE.equals(b.get("enabled")),u.get("id"),id,b.get("version"));if(changed==0)throw new ApiException(409,"资料已更新，请刷新后重试");return Map.of("ok",true);}
    @DeleteMapping("/knowledge/{id}") Object disableKnowledge(@PathVariable String id,HttpServletRequest req){var u=auth.current(req);auth.requireAdmin(u);projects.db().update("UPDATE knowledge_documents SET enabled=FALSE,version=version+1,updated_by=? WHERE id=?",u.get("id"),id);return Map.of("ok",true);}
}
