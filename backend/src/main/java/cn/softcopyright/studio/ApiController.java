package cn.softcopyright.studio;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.poi.util.Units;
import org.apache.poi.xwpf.usermodel.*;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTFonts;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.*;
import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.PreparedStatement;
import java.sql.Statement;
import java.time.LocalDateTime;
import java.util.*;
import java.util.zip.*;
import org.apache.xmlbeans.XmlCursor;

@RestController
@RequestMapping("/api")
@CrossOrigin(origins = "*")
public class ApiController {
    private static final String DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    private final JdbcTemplate db;
    private final ObjectMapper json = new ObjectMapper();
    private final Path assetRoot;
    private final String aiUrl;

    public ApiController(JdbcTemplate db, @Value("${app.asset-root}") String assetRoot, @Value("${ai.service-url}") String aiUrl) {
        this.db = db; this.assetRoot = Paths.get(assetRoot); this.aiUrl = aiUrl;
    }

    @GetMapping("/health") public Map<String, Object> health() { return Map.of("status", "ok", "time", LocalDateTime.now().toString()); }

    @GetMapping("/ai-config") public Map<String, Object> getAiConfig() {
        return readMap("select payload from app_settings where setting_key='ai'", null);
    }

    @PutMapping("/ai-config") public Map<String, Object> saveAiConfig(@RequestBody Map<String, Object> body) throws Exception {
        db.update("insert into app_settings(setting_key,payload) values('ai',?) on duplicate key update payload=values(payload)", json.writeValueAsString(body));
        return Map.of("saved", true, "aiConfig", body);
    }

    @GetMapping("/foundation") public Map<String, Object> foundation() {
        try { return readMap("select payload from project_foundations order by updated_at desc limit 1", null); }
        catch (Exception ignored) { return Map.of(); }
    }

    @PostMapping("/foundation") public Map<String, Object> saveFoundation(@RequestBody Map<String, Object> body) throws Exception {
        db.update("delete from foundation_profiles");
        db.update("insert into foundation_profiles(payload) values (?)", json.writeValueAsString(body));
        return Map.of("saved", true, "profile", body);
    }

    @PostMapping("/ai/optimize") public Object optimize(@RequestBody Map<String, Object> body) { return proxy("/optimize", body); }
    @PostMapping("/ai/test") public Object testAi(@RequestBody Map<String, Object> body) { return proxy("/test-connection", body); }
    @PostMapping("/manual/generate") public Object generate(@RequestBody Map<String, Object> body) { return proxy("/generate-manual", body); }
    @PostMapping("/manual/generate-component") public Object generateComponent(@RequestBody Map<String, Object> body) { return proxy("/generate-component", body); }
    @PostMapping("/manual/generate-full") public Object generateFull(@RequestBody Map<String, Object> body) { return proxy("/generate-full", body); }
    @PostMapping("/manual/generate-restructured") public Object generateRestructured(@RequestBody Map<String, Object> body) { return proxy("/generate-restructured", body); }

    private Object proxy(String path, Map<String, Object> body) {
        try {
            String url = aiUrl + path;
            byte[] requestBody = json.writeValueAsBytes(body);
            HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(90_000);
            connection.setRequestProperty("Content-Type", MediaType.APPLICATION_JSON_VALUE);
            connection.setFixedLengthStreamingMode(requestBody.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(requestBody); }
            int status = connection.getResponseCode();
            InputStream stream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            String responseBody = stream == null ? "" : new String(stream.readAllBytes(), StandardCharsets.UTF_8);
            Object payload = responseBody.isBlank() ? Map.of() : json.readValue(responseBody, Object.class);
            if (status >= 400) {
                Object detail = responseBody;
                if (payload instanceof Map<?, ?> map && map.containsKey("detail")) detail = map.get("detail");
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                        "AI 服务返回错误（" + status + "）：" + Objects.toString(detail, "请求失败"));
            }
            return payload;
        } catch (ResponseStatusException error) { throw error; }
        catch (Exception error) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI 服务不可用：" + Objects.toString(error.getMessage(), "请求失败"), error); }
    }

    @GetMapping("/copyrights") public List<Map<String, Object>> copyrights() {
        try { return db.queryForList("select * from copyright_records order by updated_at desc"); }
        catch (Exception ignored) { return List.of(); }
    }

    @GetMapping("/copyrights/available-manual") public List<Map<String, Object>> availableManualProjects() {
        List<Map<String, Object>> result = new ArrayList<>();
        for (Map<String, Object> item : copyrights()) {
            Map<String, Object> profile = readMap("select payload from project_foundations where copyright_id=?", item.get("id"));
            String name = Objects.toString(item.get("name"), Objects.toString(profile.get("name"), "")).trim();
            if (name.isBlank()) continue;
            result.add(Map.of("id", item.get("id"), "name", name, "version", Objects.toString(item.get("version"), Objects.toString(profile.get("version"), ""))));
        }
        return result;
    }

    @PostMapping("/copyrights") public Map<String, Object> createCopyright(@RequestBody Map<String, Object> body) {
        KeyHolder keys = new GeneratedKeyHolder();
        db.update(connection -> {
            PreparedStatement statement = connection.prepareStatement("insert into copyright_records(name, short_name, version, owner, industry, completion_date, status, asset_path) values(?,?,?,?,?,?,?,?)", Statement.RETURN_GENERATED_KEYS);
            statement.setObject(1, body.get("name")); statement.setObject(2, body.get("shortName")); statement.setObject(3, body.get("version")); statement.setObject(4, body.get("owner")); statement.setObject(5, body.get("industry")); statement.setObject(6, body.get("completionDate")); statement.setObject(7, body.getOrDefault("status", "草稿")); statement.setObject(8, body.get("assetPath")); return statement;
        }, keys);
        Map<String, Object> result = new LinkedHashMap<>(body); result.put("id", Objects.requireNonNull(keys.getKey()).longValue()); return result;
    }

    @PutMapping("/copyrights/{id}") public Map<String, Object> updateCopyright(@PathVariable long id, @RequestBody Map<String, Object> body) {
        db.update("update copyright_records set name=?, short_name=?, version=?, owner=?, industry=?, completion_date=?, status=?, asset_path=? where id=?", body.get("name"), body.get("shortName"), body.get("version"), body.get("owner"), body.get("industry"), body.get("completionDate"), body.getOrDefault("status", "草稿"), body.get("assetPath"), id); return body;
    }

    @DeleteMapping("/copyrights/{id}") public Map<String, Object> deleteCopyright(@PathVariable long id) { db.update("delete from copyright_records where id=?", id); return Map.of("deleted", true); }

    @GetMapping("/copyrights/{id}/workspace") public Map<String, Object> getWorkspace(@PathVariable long id) {
        Map<String, Object> workspace = new LinkedHashMap<>(); workspace.put("profile", readMap("select payload from project_foundations where copyright_id=?", id)); workspace.put("aiConfig", readMap("select payload from project_ai_configs where copyright_id=?", id)); workspace.put("nodes", readList("select nodes from manual_workspaces where copyright_id=?", id)); workspace.put("connections", readList("select connections from manual_workspaces where copyright_id=?", id)); workspace.put("generated", readMap("select `generated` from manual_workspaces where copyright_id=?", id)); return workspace;
    }

    @PutMapping("/copyrights/{id}/workspace") public Map<String, Object> saveWorkspace(@PathVariable long id, @RequestBody Map<String, Object> body) throws Exception {
        String profile = json.writeValueAsString(body.getOrDefault("profile", Map.of())), aiConfig = json.writeValueAsString(body.getOrDefault("aiConfig", Map.of())), nodes = json.writeValueAsString(body.getOrDefault("nodes", List.of())), connections = json.writeValueAsString(body.getOrDefault("connections", List.of())), generated = json.writeValueAsString(body.getOrDefault("generated", Map.of()));
        db.update("insert into project_foundations(copyright_id,payload) values(?,?) on duplicate key update payload=values(payload)", id, profile);
        db.update("insert into project_ai_configs(copyright_id,payload) values(?,?) on duplicate key update payload=values(payload)", id, aiConfig);
        db.update("insert into manual_workspaces(copyright_id,nodes,connections,`generated`) values(?,?,?,?) on duplicate key update nodes=values(nodes),connections=values(connections),`generated`=values(`generated`)", id, nodes, connections, generated);
        return Map.of("saved", true, "copyrightId", id);
    }

    @PostMapping(value = "/copyrights/{id}/materials", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, Object> uploadMaterials(@PathVariable long id, @RequestParam("files") MultipartFile[] files) throws IOException {
        Path target = assetRoot.resolve("copyright-" + id).normalize(); Files.createDirectories(target);
        for (MultipartFile file : files) { String original = Objects.requireNonNullElse(file.getOriginalFilename(), "material.bin").replace('\\', '/'); Path relative = Paths.get(original).normalize(); if (relative.isAbsolute() || relative.startsWith("..")) relative = relative.getFileName(); Path destination = target.resolve(relative).normalize(); if (!destination.startsWith(target)) continue; Files.createDirectories(Objects.requireNonNull(destination.getParent())); file.transferTo(destination); }
        String relative = target.toString(); db.update("update copyright_records set asset_path=? where id=?", relative, id); return Map.of("assetPath", relative, "count", files.length);
    }

    @GetMapping("/copyrights/{id}/materials/download") public ResponseEntity<byte[]> downloadMaterials(@PathVariable long id) throws IOException {
        Path target = assetRoot.resolve("copyright-" + id).normalize(); if (!Files.isDirectory(target)) return ResponseEntity.notFound().build(); ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(output); var paths = Files.walk(target)) { paths.filter(Files::isRegularFile).forEach(path -> { try { zip.putNextEntry(new ZipEntry(target.relativize(path).toString().replace('\\', '/'))); Files.copy(path, zip); zip.closeEntry(); } catch (IOException error) { throw new UncheckedIOException(error); } }); } catch (UncheckedIOException error) { throw error.getCause(); }
        HttpHeaders headers = new HttpHeaders(); headers.setContentType(MediaType.parseMediaType("application/zip")); headers.setContentDisposition(ContentDisposition.attachment().filename("copyright-" + id + "-materials.zip", StandardCharsets.UTF_8).build()); return new ResponseEntity<>(output.toByteArray(), headers, HttpStatus.OK);
    }

    @GetMapping("/copyrights/{id}/export") public ResponseEntity<byte[]> exportWord(@PathVariable long id) throws Exception {
        Map<String, Object> workspace = getWorkspace(id); Map<String, Object> project = db.queryForMap("select * from copyright_records where id=?", id);
        List<Map<String, Object>> nodeList = castList(workspace.get("nodes")), connectionList = castList(workspace.get("connections")); Map<String, Object> generatedData = castMap(workspace.get("generated"));
        Map<String, Map<String, Object>> byId = new LinkedHashMap<>(); nodeList.forEach(node -> byId.put(Objects.toString(node.get("id")), node));
        Path templatePath = Paths.get("src/main/resources/templates/操作手册模板.docx"); if (!Files.exists(templatePath)) templatePath = Paths.get("backend/src/main/resources/templates/操作手册模板.docx");
        ByteArrayOutputStream docx = new ByteArrayOutputStream();
        try (InputStream template = Files.newInputStream(templatePath); XWPFDocument document = new XWPFDocument(template)) {
            prepareTemplate(document, project, workspace, nodeList, connectionList);
            Set<String> visited = new HashSet<>(); List<Map<String, Object>> ordered = new ArrayList<>(nodeList); ordered.sort(Comparator.comparingDouble((Map<String, Object> n) -> number(n.get("y"))).thenComparingDouble(n -> number(n.get("x"))));
            Set<String> incoming = new HashSet<>(); for (Map<String, Object> link : connectionList) incoming.add(Objects.toString(link.get("toId")));
            for (Map<String, Object> node : ordered) if (!incoming.contains(Objects.toString(node.get("id")))) walkDocument(document, node, byId, connectionList, generatedData, visited, headingLevel(node), null);
            for (Map<String, Object> node : ordered) if (!visited.contains(Objects.toString(node.get("id")))) walkDocument(document, node, byId, connectionList, generatedData, visited, headingLevel(node), null);
            document.write(docx);
        }
        ByteArrayOutputStream archive = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(archive)) {
            zip.putNextEntry(new ZipEntry("操作手册.docx")); zip.write(docx.toByteArray()); zip.closeEntry();
            zip.putNextEntry(new ZipEntry("基础信息.txt")); zip.write(buildBasicInfo(workspace, project).getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
        }
        HttpHeaders headers = new HttpHeaders(); headers.setContentType(MediaType.parseMediaType("application/zip")); headers.setContentDisposition(ContentDisposition.attachment().filename("软著材料.zip", StandardCharsets.UTF_8).build()); return new ResponseEntity<>(archive.toByteArray(), headers, HttpStatus.OK);
    }

    private void prepareTemplate(XWPFDocument document, Map<String, Object> project, Map<String, Object> workspace, List<Map<String, Object>> nodes, List<Map<String, Object>> links) {
        // Resolve and rewrite every template placeholder before changing the body XML.
        // POI paragraph wrappers become orphaned when a sibling is inserted or removed.
        List<XWPFParagraph> paragraphs = new ArrayList<>(document.getParagraphs());
        String name = Objects.toString(project.get("name"), Objects.toString(castMap(workspace.get("profile")).get("name"), "软件操作手册"));
        if (paragraphs.size() > 6) replaceParagraph(paragraphs.get(6), name);
        if (paragraphs.size() > 7) replaceParagraph(paragraphs.get(7), "操作手册");
        if (paragraphs.size() > 18) replaceParagraph(paragraphs.get(18), Objects.toString(project.get("owner"), ""));

        XWPFParagraph introParagraph = paragraphs.size() > 52 ? paragraphs.get(52) : null;
        XWPFParagraph environmentParagraph = paragraphs.size() > 54 ? paragraphs.get(54) : null;
        XWPFParagraph[] environmentRows = new XWPFParagraph[6];
        for (int i = 0; i < environmentRows.length && 55 + i < paragraphs.size(); i++) environmentRows[i] = paragraphs.get(55 + i);
        Map<String, Object> profile = castMap(workspace.get("profile"));
        if (introParagraph != null) replaceParagraph(introParagraph, Objects.toString(profile.get("purpose"), ""));
        if (environmentParagraph != null) replaceParagraph(environmentParagraph, "运行的硬件、软件环境的描述如下：");
        String[] env = {"服务端操作系统：", "服务端运行环境：", "数据库支持：", "协议支持：", "硬件支持：", "客户端要求："};
        String[] keys = {"runOs", "runHardware", "support", "languages", "runHardware", "support"};
        for (int i = 0; i < env.length && environmentRows[i] != null; i++) replaceParagraph(environmentRows[i], env[i] + Objects.toString(profile.get(keys[i]), "") + "；");

        List<String> toc = new ArrayList<>();
        toc.add("一、 系统简介"); toc.add("二、 运行环境");
        List<Map<String, Object>> ordered = new ArrayList<>(nodes);
        ordered.sort(Comparator.comparingDouble((Map<String, Object> n) -> number(n.get("y"))).thenComparingDouble(n -> number(n.get("x"))));
        Set<String> incoming = new HashSet<>();
        for (Map<String, Object> link : links) incoming.add(Objects.toString(link.get("toId")));
        int rootIndex = 3;
        for (Map<String, Object> node : ordered) if (!incoming.contains(Objects.toString(node.get("id")))) {
            String root = chineseNumber(rootIndex) + "、 ";
            toc.add(root + tocTitle(node, workspace));
            addTocChildren(toc, node, nodes, links, String.valueOf(rootIndex), 1, workspace); rootIndex++;
        }
        int tocStart = 24; int tocRows = Math.max(0, Math.min(48, paragraphs.size()) - tocStart);
        for (int i = 0; i < tocRows && i < toc.size(); i++) replaceTocParagraph(paragraphs.get(tocStart + i), toc.get(i));
        for (int i = Math.min(toc.size(), tocRows); i < tocRows; i++) replaceTocParagraph(paragraphs.get(tocStart + i), "");

        // Add overflow TOC rows immediately before the reference body marker. No
        // paragraph wrapper is used after this point, so inserted XML stays valid.
        if (toc.size() > tocRows && paragraphs.size() > 51) {
            XWPFParagraph anchor = paragraphs.get(51);
            for (int i = tocRows; i < toc.size(); i++) {
                XmlCursor cursor = anchor.getCTP().newCursor();
                XWPFParagraph extra = document.insertNewParagraph(cursor);
                extra.setStyle("26"); replaceTocParagraph(extra, toc.get(i)); cursor.dispose();
            }
        }
        // Keep the cover, TOC, introduction and environment rows, then remove
        // the template's sample component body. Locate the environment row again
        // after TOC insertion because its body index has shifted.
        int lastEnvironment = environmentRows[environmentRows.length - 1] == null ? 60 : document.getBodyElements().indexOf(environmentRows[environmentRows.length - 1]);
        List<IBodyElement> elements = new ArrayList<>(document.getBodyElements());
        for (int i = elements.size() - 1; i > lastEnvironment; i--) document.removeBodyElement(i);
    }

    private void addTocNames(List<String> out, Map<String, Object> node, List<Map<String, Object>> nodes, List<Map<String, Object>> links, String number, int depth) { out.add(number + " " + Objects.toString(node.get("name"), "未命名组件")); List<Map<String, Object>> children = new ArrayList<>(); for (Map<String, Object> link : links) if (Objects.toString(node.get("id")).equals(Objects.toString(link.get("fromId")))) for (Map<String, Object> item : nodes) if (Objects.toString(item.get("id")).equals(Objects.toString(link.get("toId")))) children.add(item); children.sort(Comparator.comparingDouble((Map<String, Object> n) -> number(n.get("y"))).thenComparingDouble(n -> number(n.get("x")))); for (int i = 0; i < children.size(); i++) addTocNames(out, children.get(i), nodes, links, number + "." + (i + 1), depth + 1); }
    private void addTocChildren(List<String> out, Map<String, Object> node, List<Map<String, Object>> nodes, List<Map<String, Object>> links, String prefix, int depth, Map<String, Object> workspace) { List<Map<String, Object>> children = new ArrayList<>(); for (Map<String, Object> link : links) if (Objects.toString(node.get("id")).equals(Objects.toString(link.get("fromId")))) for (Map<String, Object> item : nodes) if (Objects.toString(item.get("id")).equals(Objects.toString(link.get("toId")))) children.add(item); children.sort(Comparator.comparingDouble((Map<String, Object> n) -> number(n.get("y"))).thenComparingDouble(n -> number(n.get("x")))); for (int i = 0; i < children.size(); i++) { String number = prefix + "." + (i + 1); out.add(number + " " + tocTitle(children.get(i), workspace)); addTocChildren(out, children.get(i), nodes, links, number, depth + 1, workspace); } }
    private String tocTitle(Map<String, Object> node, Map<String, Object> workspace) { Map<String, Object> generated = castMap(workspace.get("generated")); Map<String, Object> bucket = castMap(generated.get(("screenshot".equals(Objects.toString(node.get("type"))) || "screenshot-group".equals(Objects.toString(node.get("type")))) ? "screenshots" : "nodes")); Map<String, Object> item = castMap(bucket.get(Objects.toString(node.get("id")))); return titleFor(item, Objects.toString(node.get("name"), "未命名组件")); }
    private void replaceTocParagraph(XWPFParagraph paragraph, String value) {
        if (paragraph == null) return;
        if (value != null && !value.isBlank()) paragraph.setStyle(tocStyle(value));
        replaceParagraph(paragraph, value);
        if (value != null && !value.isEmpty()) {
            XWPFRun tab = paragraph.createRun(); tab.addTab();
            paragraph.createRun().setText("1");
        }
    }
    private String tocStyle(String value) {
        int space = value.indexOf(' '); String prefix = space > 0 ? value.substring(0, space) : value;
        int depth = prefix.contains("、") ? 1 : prefix.split("\\.").length;
        return switch (Math.min(Math.max(depth, 1), 4)) { case 1 -> "26"; case 2 -> "30"; case 3 -> "19"; default -> "27"; };
    }

    private void replaceParagraph(XWPFParagraph paragraph, String value) {
        if (paragraph == null) return;
        org.w3c.dom.Node root = paragraph.getCTP().getDomNode();
        for (org.w3c.dom.Node child = root.getFirstChild(); child != null;) {
            org.w3c.dom.Node next = child.getNextSibling();
            if (!"pPr".equals(child.getLocalName())) root.removeChild(child);
            child = next;
        }
        if (value != null && !value.isEmpty()) paragraph.createRun().setText(value);
    }
    private String buildBasicInfo(Map<String, Object> workspace, Map<String, Object> project) { StringBuilder out = new StringBuilder(); Map<String, Object> profile = castMap(workspace.get("profile")); for (Map.Entry<String, Object> entry : profile.entrySet()) out.append(fieldLabel(entry.getKey())).append("：").append(Objects.toString(entry.getValue(), "")).append('\n'); if (out.length() == 0) out.append("软件全称：").append(Objects.toString(project.get("name"), "")).append('\n'); return out.toString(); }

    private void walkDocument(XWPFDocument document, Map<String, Object> node, Map<String, Map<String, Object>> byId, List<Map<String, Object>> connections, Map<String, Object> generatedData, Set<String> visited, int level, String parentType) throws Exception {
        String id = Objects.toString(node.get("id")); if (!visited.add(id)) return; String type = Objects.toString(node.get("type")); String name = Objects.toString(node.get("name"), "未命名组件"); Map<String, Object> data = generatedFor(generatedData, node); if ("screenshot".equals(type) || "screenshot-group".equals(type)) {
            if ("screenshot".equals(type)) {
                boolean chained = connections.stream().anyMatch(link -> id.equals(Objects.toString(link.get("toId"))) && "screenshot".equals(Objects.toString(byId.get(Objects.toString(link.get("fromId"))).get("type"))));
                if (chained) return;
                addHeading(document, titleFor(data, name), level); addParagraph(document, screenshotOperation(data)); addImage(document, Objects.toString(node.get("image"), ""));
                String currentId = id;
                while (true) {
                    String parentId = currentId;
                    String nextId = connections.stream().filter(link -> parentId.equals(Objects.toString(link.get("fromId"))))
                        .map(link -> Objects.toString(link.get("toId"))).filter(next -> byId.containsKey(next) && "screenshot".equals(Objects.toString(byId.get(next).get("type")))).min(Comparator.comparingDouble(next -> number(byId.get(next).get("y")))).orElse(null);
                    if (nextId == null || !visited.add(nextId)) break;
                    Map<String, Object> nextNode = byId.get(nextId); Map<String, Object> nextData = generatedFor(generatedData, nextNode); addHeading(document, titleFor(nextData, Objects.toString(nextNode.get("name"), "截图")), level); addParagraph(document, screenshotOperation(nextData)); addImage(document, Objects.toString(nextNode.get("image"), "")); currentId = nextId;
                }
            } else {
                addHeading(document, titleFor(data, name), level); addParagraph(document, screenshotOperation(data)); addImage(document, Objects.toString(node.get("image"), ""));
            }
            return;
        }
        addHeading(document, titleFor(data, name), level); addParagraph(document, Objects.toString(data.get("contentSummary"), "")); List<Map<String, Object>> childNodes = new ArrayList<>(); for (Map<String, Object> connection : connections) if (id.equals(Objects.toString(connection.get("fromId")))) { Map<String, Object> child = byId.get(Objects.toString(connection.get("toId"))); if (child != null) childNodes.add(child); } childNodes.sort(Comparator.comparingDouble((Map<String, Object> n) -> number(n.get("y"))).thenComparingDouble(n -> number(n.get("x")))); for (Map<String, Object> child : childNodes) walkDocument(document, child, byId, connections, generatedData, visited, level + 1, type);
    }
    private double number(Object value) { try { return Double.parseDouble(Objects.toString(value, "0")); } catch (NumberFormatException ignored) { return 0; } }
    private String chineseNumber(int value) { String[] digits = {"零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"}; return value >= 0 && value < digits.length ? digits[value] : String.valueOf(value); }
    private Map<String, Object> generatedFor(Map<String, Object> generated, Map<String, Object> node) { String type = Objects.toString(node.get("type")), id = Objects.toString(node.get("id")); Map<String, Object> bucket = castMap(generated.get(("screenshot".equals(type) || "screenshot-group".equals(type)) ? "screenshots" : "nodes")); return castMap(bucket.get(id)); }
    private String screenshotOperation(Map<String, Object> data) {
        String operation = Objects.toString(data.get("operation"), "").trim();
        if (operation.isBlank()) operation = Objects.toString(data.get("contentSummary"), "").trim();
        operation = operation.replaceFirst("^截图内容\\s*[:：]\\s*", "").trim();
        return operation.startsWith("【") && operation.endsWith("】") ? operation.substring(1, operation.length() - 1).trim() : operation;
    }
    private String titleFor(Map<String, Object> data, String fallback) { String title = Objects.toString(data.get("title"), "").trim(); return title.isBlank() ? (fallback.isBlank() ? "功能操作界面" : fallback) : title; }
    private int headingLevel(Map<String, Object> node) { return switch (Objects.toString(node.get("type"))) { case "system" -> 1; case "module" -> 2; default -> 3; }; }
    private void applyDocumentFonts(XWPFDocument document) {
        XWPFStyles styles = document.getStyles();
        if (styles == null) styles = document.createStyles();
        for (String styleId : List.of("Normal", "Title", "Heading1", "Heading2", "Heading3")) {
            XWPFStyle style = styles.getStyle(styleId);
            if (style == null) continue;
            var rPr = style.getCTStyle().isSetRPr() ? style.getCTStyle().getRPr() : style.getCTStyle().addNewRPr();
            CTFonts fonts = rPr.addNewRFonts(); fonts.setAscii("Arial"); fonts.setHAnsi("Arial"); fonts.setEastAsia("Arial Unicode MS");
        }
        for (XWPFParagraph paragraph : document.getParagraphs()) for (XWPFRun run : paragraph.getRuns()) run.setFontFamily("Arial Unicode MS");
        for (XWPFTable table : document.getTables()) for (XWPFTableRow row : table.getRows()) for (XWPFTableCell cell : row.getTableCells()) for (XWPFParagraph paragraph : cell.getParagraphs()) for (XWPFRun run : paragraph.getRuns()) run.setFontFamily("Arial Unicode MS");
    }
    private void addHeading(XWPFDocument document, String text, int level) { XWPFParagraph paragraph = document.createParagraph(); paragraph.setStyle(String.valueOf(Math.min(Math.max(level, 1) + 1, 9))); paragraph.createRun().setText(text); }
    private void addParagraph(XWPFDocument document, String text) {
        for (String line : text.split("\\R", -1)) document.createParagraph().createRun().setText(line);
    }
    private String fieldLabel(String key) { return switch (key) { case "name" -> "软件全称"; case "shortName" -> "软件简称"; case "version" -> "版本号"; case "acquisition" -> "权利取得方式"; case "rights" -> "权利范围"; case "publication" -> "发表状态"; case "completionDate" -> "开发完成日期"; case "owner" -> "著作权人"; case "category" -> "软件分类"; case "development" -> "开发方式"; case "languages" -> "编程语言"; case "purpose" -> "开发目的"; case "industry" -> "面向行业 / 领域"; case "function" -> "软件的主要功能"; case "feature" -> "软件的技术特点"; case "devHardware" -> "开发硬件环境"; case "runHardware" -> "运行硬件环境"; case "devOs" -> "开发操作系统"; case "devTools" -> "开发环境 / 工具"; case "runOs" -> "运行平台 / 操作系统"; case "support" -> "运行支撑环境 / 支持软件"; case "sourceLines" -> "源程序量"; default -> key; }; }
    private void addImage(XWPFDocument document, String dataUrl) throws Exception {
        if (!dataUrl.startsWith("data:image/")) return; String[] parts = dataUrl.split(",", 2); if (parts.length != 2) return;
        byte[] bytes = Base64.getDecoder().decode(parts[1]); String mime = parts[0].toLowerCase(Locale.ROOT); int type; String fileName; byte[] pictureBytes = bytes;
        if (mime.contains("png")) { type = Document.PICTURE_TYPE_PNG; fileName = "截图.png"; }
        else if (mime.contains("jpeg") || mime.contains("jpg")) { type = Document.PICTURE_TYPE_JPEG; fileName = "截图.jpg"; }
        else {
            BufferedImage image = ImageIO.read(new ByteArrayInputStream(bytes)); if (image == null) return;
            ByteArrayOutputStream converted = new ByteArrayOutputStream(); ImageIO.write(image, "png", converted); pictureBytes = converted.toByteArray(); type = Document.PICTURE_TYPE_PNG; fileName = "截图.png";
        }
        XWPFRun run = document.createParagraph().createRun(); run.addPicture(new ByteArrayInputStream(pictureBytes), type, fileName, Units.toEMU(460), Units.toEMU(280));
    }
    private boolean profileComplete(Map<String, Object> profile) { return List.of("name", "version", "owner", "purpose", "function", "feature").stream().allMatch(key -> Objects.toString(profile.get(key), "").trim().length() > 0); }
    private Map<String, Object> readMap(String sql, Object parameter) { try { String value = parameter == null ? db.queryForObject(sql, String.class) : db.queryForObject(sql, String.class, parameter); return value == null ? new LinkedHashMap<>() : json.readValue(value, new TypeReference<Map<String, Object>>() {}); } catch (Exception ignored) { return new LinkedHashMap<>(); } }
    private List<Map<String, Object>> readList(String sql, Object parameter) { try { String value = db.queryForObject(sql, String.class, parameter); return value == null ? new ArrayList<>() : json.readValue(value, new TypeReference<List<Map<String, Object>>>() {}); } catch (Exception ignored) { return new ArrayList<>(); } }
    private Map<String, Object> castMap(Object value) { return value instanceof Map<?, ?> map ? (Map<String, Object>) map : new LinkedHashMap<>(); }
    private List<Map<String, Object>> castList(Object value) { return value instanceof List<?> list ? (List<Map<String, Object>>) list : new ArrayList<>(); }
}
