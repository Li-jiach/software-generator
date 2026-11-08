package cn.softcopyright.studio;

import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.util.*;
import java.util.zip.ZipInputStream;

import static org.junit.jupiter.api.Assertions.*;

class ScreenshotExportTest {
    @Test
    void exportPreservesButtonInstructionsImagesAndTemplate() throws Exception {
        ByteArrayOutputStream image = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(2, 2, BufferedImage.TYPE_INT_RGB), "png", image);
        String dataUrl = "data:image/png;base64," + Base64.getEncoder().encodeToString(image.toByteArray());
        String operation = "1. 点击“查询”按钮，按已填写的条件查询列表。\n2. 点击“重置”按钮，清空查询条件。";
        List<Map<String, Object>> nodes = List.of(
                Map.of("id", "system", "type", "system", "name", "业务系统", "y", 0),
                Map.of("id", "module", "type", "module", "name", "查询模块", "y", 10),
                Map.of("id", "page", "type", "page", "name", "查询页面", "y", 20),
                Map.of("id", "new", "type", "screenshot", "name", "记录查询", "image", dataUrl, "y", 0),
                Map.of("id", "old", "type", "screenshot", "name", "历史查询", "image", dataUrl, "y", 100));
        Map<String, Object> screenshots = Map.of(
                "new", Map.of("title", "记录查询", "contentSummary", "界面概述不会替代详细操作。", "operation", operation),
                "old", Map.of("title", "历史查询", "contentSummary", "界面概述", "operation", "截图内容：【" + operation + "】"));
        Map<String, Object> introductions = Map.of(
                "system", Map.of("contentSummary", "系统介绍正文", "operation", "旧系统操作介绍"),
                "module", Map.of("contentSummary", "模块介绍正文", "operation", "旧模块操作介绍"),
                "page", Map.of("contentSummary", "页面介绍正文", "operation", "旧页面操作介绍"));
        List<Map<String, Object>> links = List.of(
                Map.of("fromId", "system", "toId", "module"), Map.of("fromId", "module", "toId", "page"),
                Map.of("fromId", "page", "toId", "new"), Map.of("fromId", "page", "toId", "old"));
        Map<String, Object> workspace = Map.of("nodes", nodes, "connections", links,
                "profile", Map.of("name", "查询软件", "owner", "测试著作权人"),
                "generated", Map.of("nodes", introductions, "screenshots", screenshots));
        JdbcTemplate db = new JdbcTemplate() {
            @Override public Map<String, Object> queryForMap(String sql, Object... args) {
                return Map.of("name", "查询软件");
            }
        };
        ApiController controller = new ApiController(db, "target/test-assets", "http://localhost:8090") {
            @Override public Map<String, Object> getWorkspace(long id) { return workspace; }
        };
        Map<String, byte[]> files = new LinkedHashMap<>();
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(controller.exportWord(1).getBody()))) {
            for (var entry = zip.getNextEntry(); entry != null; entry = zip.getNextEntry()) files.put(entry.getName(), zip.readAllBytes());
        }
        assertEquals(Set.of("操作手册.docx", "基础信息.txt"), files.keySet());
        try (XWPFDocument document = new XWPFDocument(new ByteArrayInputStream(files.get("操作手册.docx")))) {
            String body = String.join("\n", document.getParagraphs().stream().map(p -> p.getText()).toList());
            assertFalse(body.contains("截图内容"));
            assertFalse(body.contains("界面概述不会替代详细操作"));
            assertFalse(body.contains("旧系统操作介绍"));
            assertFalse(body.contains("旧模块操作介绍"));
            assertFalse(body.contains("旧页面操作介绍"));
            assertTrue(body.contains("系统介绍正文"));
            assertTrue(body.indexOf("系统介绍正文") < body.indexOf("模块介绍正文"));
            assertTrue(body.indexOf("模块介绍正文") < body.indexOf("页面介绍正文"));
            assertTrue(body.indexOf("页面介绍正文") < body.indexOf(operation));
            assertEquals(2, body.split("点击“查询”按钮", -1).length - 1);
            assertEquals(2, body.split("点击“重置”按钮", -1).length - 1);
            assertTrue(body.contains(operation));
            assertFalse(document.getAllPictures().isEmpty());
            assertFalse(document.getHeaderList().isEmpty());
            assertFalse(document.getFooterList().isEmpty());
        }
    }
}
