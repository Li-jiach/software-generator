package cn.copyright.workspace;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.io.ByteArrayOutputStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.function.BiConsumer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
class AssistantBridge {
    final ObjectMapper json;
    final HttpClient client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(5)).build();
    @Value("${app.ai-url}") String baseUrl;
    @Value("${app.service-token}") String token;
    AssistantBridge(ObjectMapper json) {this.json=json;}
    Map<String,Object> request(String method,String path,Object data) {
        try {
            var body=data==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(data));
            return send(HttpRequest.newBuilder(URI.create(baseUrl+path)).timeout(Duration.ofSeconds(310)).header("X-Service-Token",token).header("Content-Type","application/json").method(method,body).build());
        } catch(ApiException e){throw e;}catch(Exception e){throw new ApiException(503,"软著助手服务暂时不可用，请检查Python服务是否启动");}
    }
    Map<String,Object> send(HttpRequest request) throws Exception {
        var r=client.send(request,HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        Map<String,Object> result=json.readValue(r.body(),new TypeReference<>(){});
        if(r.statusCode()>=400)throw new ApiException(r.statusCode(),result.get("detail") instanceof String s?s:"助手请求参数不合法");
        return result;
    }
    Map<String,Object> answer(Object data, BiConsumer<String,Map<String,Object>> events) {
        if(events==null)return request("POST","/chat",data);
        try {
            var req=HttpRequest.newBuilder(URI.create(baseUrl+"/chat/stream")).timeout(Duration.ofSeconds(310))
                .header("X-Service-Token",token).header("Content-Type","application/json")
                .POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(data))).build();
            var response=client.send(req,HttpResponse.BodyHandlers.ofInputStream());
            try(var reader=new BufferedReader(new InputStreamReader(response.body(),StandardCharsets.UTF_8))){
                String line;
                while((line=reader.readLine())!=null){
                    Map<String,Object> event=json.readValue(line,new TypeReference<>(){});
                    if(response.statusCode()>=400)throw new ApiException(response.statusCode(),
                        event.get("detail") instanceof String detail?detail:"助手流式请求失败");
                    String type=ProjectService.text(event,"type");
                    switch(type){
                        case "ready","delta":events.accept(type,event);break;
                        case "done":event.remove("type");return event;
                        case "error":throw new ApiException(502,ProjectService.text(event,"message"));
                        default:throw new ApiException(502,"助手返回了无效的流式事件");
                    }
                }
            }
            throw new ApiException(502,"助手回答中断，请重试");
        }catch(ApiException e){throw e;}
        catch(InterruptedException e){Thread.currentThread().interrupt();throw new ApiException(503,"助手请求已中断");}
        catch(java.io.IOException e){throw new ApiException(503,"无法连接助手流式服务");}
    }
    byte[] download(String path,Object data) {
        try {
            var req=HttpRequest.newBuilder(URI.create(baseUrl+path)).timeout(Duration.ofSeconds(60))
                .header("X-Service-Token",token).header("Content-Type","application/json")
                .POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(data))).build();
            var response=client.send(req,HttpResponse.BodyHandlers.ofInputStream());
            try (var in=response.body()) {
                if(response.statusCode()!=200)throw new ApiException(response.statusCode(),"当前任务的文件不可下载");
                byte[] result=in.readNBytes(52_000_001);
                if(result.length>52_000_000)throw new ApiException(413,"生成文件超过下载上限");
                return result;
            }
        }catch(ApiException e){throw e;}catch(Exception e){throw new ApiException(503,"无法下载手册任务文件");}
    }
    byte[] officialPdf(String suffix, byte[] file, boolean excerpt) {
        try {
            var req=HttpRequest.newBuilder(URI.create(baseUrl+"/official/material-pdf?suffix="+suffix+"&excerpt="+excerpt))
                .timeout(Duration.ofSeconds(70)).header("X-Service-Token",token)
                .header("Content-Type","application/octet-stream")
                .POST(HttpRequest.BodyPublishers.ofByteArray(file)).build();
            var response=client.send(req,HttpResponse.BodyHandlers.ofInputStream());
            try(var in=response.body()) {
                if(response.statusCode()!=200) {
                    var error=json.readTree(in.readNBytes(8192));
                    throw new ApiException(response.statusCode(),error.path("detail").asText("附件转换失败"));
                }
                var pdf=in.readNBytes(20*1024*1024+1);
                if(pdf.length>20*1024*1024)throw new ApiException(422,"转换后的 PDF 超过官网 20 MB 上限");
                return pdf;
            }
        }catch(ApiException e){throw e;}
        catch(InterruptedException e){Thread.currentThread().interrupt();throw new ApiException(503,"附件转换已中断");}
        catch(Exception e){throw new ApiException(503,"附件转换服务暂不可用");}
    }

    Map<String,Object> extract(String name,byte[] bytes) {
        try {
            String boundary="Copyright-"+UUID.randomUUID();
            var out=new ByteArrayOutputStream();
            String safe=name.replaceAll("[\r\n\"\\\\]","_");
            out.write(("--"+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\""+safe+"\"\r\nContent-Type: application/octet-stream\r\n\r\n").getBytes(StandardCharsets.UTF_8));
            out.write(bytes);out.write(("\r\n--"+boundary+"--\r\n").getBytes(StandardCharsets.UTF_8));
            return send(HttpRequest.newBuilder(URI.create(baseUrl+"/extract")).timeout(Duration.ofSeconds(60)).header("X-Service-Token",token).header("Content-Type","multipart/form-data; boundary="+boundary).POST(HttpRequest.BodyPublishers.ofByteArray(out.toByteArray())).build());
        }catch(Exception e){return Map.of("text","","warning","文本提取暂不可用，原件已保存，可稍后重新提取");}
    }
}
