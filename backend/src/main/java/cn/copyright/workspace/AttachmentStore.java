package cn.copyright.workspace;

import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.zip.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.*;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

@Service
class AttachmentStore {
    final Path directory;
    final AssistantBridge ai;
    AttachmentStore(@Value("${ATTACHMENT_DIR:data/attachments}") String directory, AssistantBridge ai) {
        this.directory = Path.of(directory).toAbsolutePath().normalize();
        this.ai = ai;
    }
    Map<String,Object> store(String id, MultipartFile file) throws Exception {
        Files.createDirectories(directory);
        Path target = directory.resolve(id);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (var in = new DigestInputStream(file.getInputStream(), digest)) {
            Files.copy(in, target);
        } catch (Exception e) {
            Files.deleteIfExists(target);
            throw e;
        }
        return Map.of("path", target.toString(), "sha", HexFormat.of().formatHex(digest.digest()));
    }
    Resource resource(Map<String,Object> file) {
        if (file.get("storage_path") != null) return new FileSystemResource(path(file));
        return new ByteArrayResource((byte[])file.get("content"));
    }
    Path path(Map<String,Object> file) {
        Path path = Path.of(String.valueOf(file.get("storage_path"))).toAbsolutePath().normalize();
        if (!path.getParent().equals(directory)) throw new ApiException(400,"附件存储路径不合法");
        return path;
    }
    Map<String,Object> extract(Map<String,Object> file) {
        String name = String.valueOf(file.get("name"));
        try {
            if (name.toLowerCase(Locale.ROOT).endsWith(".zip")) {
                StringBuilder text = new StringBuilder();
                // Read bounded entries directly from ZIP, never unpack paths onto disk.
                try (ZipFile zip = new ZipFile(path(file).toFile())) {
                    var entries = zip.entries();
                    int indexed=0;
                    while (entries.hasMoreElements() && text.length()<280000 && indexed++<30) {
                        var entry=entries.nextElement();
                        if (entry.isDirectory()) continue;
                        text.append("\n文件：").append(entry.getName()).append('\n');
                    }
                }
                return Map.of("text",text.substring(0,Math.min(300000,text.length())),"warning","ZIP原件已保存，助手可按需浏览目录和读取文件");
            }
            try(var in=resource(file).getInputStream()){return ai.extract(name,in.readAllBytes());}
        } catch(Exception e) { return Map.of("text","","warning","原件已保存，文本提取失败，可稍后重试"); }
    }
    Object zipEntry(Map<String,Object> file, String entryName, int offset) {
        if(file.get("storage_path")==null || !String.valueOf(file.get("name")).toLowerCase().endsWith(".zip"))
            throw new ApiException(400,"请选择ZIP附件");
        try(ZipFile zip=new ZipFile(path(file).toFile())) {
            if(entryName.isBlank()) {
                var names=zip.stream().skip(offset).limit(100).map(e->Map.of("name",e.getName(),"size",e.getSize())).toList();
                return Map.of("entries",names,"offset",offset,"nextOffset",offset+names.size(),"total",zip.size());
            }
            var entry=zip.getEntry(entryName);
            if(entry==null||entry.isDirectory())throw new ApiException(404,"ZIP条目不存在");
            if(entry.getSize()>20*1024*1024)throw new ApiException(400,"单个压缩条目超过文本解析范围，请单独提供文本");
            try(var in=zip.getInputStream(entry)) {
                byte[] bytes=in.readNBytes(20*1024*1024+1);
                if(bytes.length>20*1024*1024)throw new ApiException(400,"条目展开内容超过解析范围");
                var extracted=ai.extract(entryName,bytes);
                String text=String.valueOf(extracted.getOrDefault("text",""));
                int start=Math.min(offset,text.length()),end=Math.min(start+16000,text.length());
                return Map.of("text",text.substring(start,end),"nextOffset",end,"total",text.length(),"entry",entryName,"warning",extracted.getOrDefault("warning",""));
            }
        }catch(ApiException e){throw e;}catch(Exception e){throw new ApiException(400,"无法读取ZIP，请检查文件是否损坏或加密");}
    }
}
