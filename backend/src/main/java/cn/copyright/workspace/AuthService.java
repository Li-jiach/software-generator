package cn.copyright.workspace;

import jakarta.annotation.PostConstruct;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
class AuthService {
    final JdbcTemplate db;
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
    private final SecureRandom random = new SecureRandom();
    private final Map<String, long[]> attempts = new ConcurrentHashMap<>();
    @Value("${app.bootstrap-password}") String bootstrapPassword;
    AuthService(JdbcTemplate db) { this.db = db; }

    @PostConstruct
    void bootstrap() {
        if (db.queryForObject("SELECT COUNT(*) FROM users", Long.class) != 0) return;
        if (bootstrapPassword == null || bootstrapPassword.length() < 12)
            throw new IllegalStateException("首次启动请设置至少12位BOOTSTRAP_PASSWORD");
        String hash = encoder.encode(bootstrapPassword);
        String[][] users = {{"admin","系统管理员","admin","管理办公室"}, {"adminDept","行政业务办","adminDept","行政业务办"}, {"research","研发中心","research","研发中心"}};
        for (var u : users) db.update("INSERT INTO users(id,username,password_hash,display_name,role,department) VALUES(?,?,?,?,?,?)", UUID.randomUUID().toString(), u[0],hash,u[1],u[2],u[3]);
    }

    static String hash(String s) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8))); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }

    Map<String,Object> current(HttpServletRequest request) {
        String token = cookie(request);
        if (token.isEmpty()) throw new ApiException(401,"请登录后继续");
        var rows = db.queryForList("SELECT u.id,u.username,u.display_name AS displayName,u.role,u.department FROM user_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>CURRENT_TIMESTAMP AND u.enabled=TRUE", hash(token));
        if (rows.isEmpty()) throw new ApiException(401,"登录已过期，请重新登录");
        return rows.get(0);
    }

    String cookie(HttpServletRequest r) {
        if (r.getCookies() != null) for (var c:r.getCookies()) if (c.getName().equals("COPYRIGHT_SESSION")) return c.getValue();
        return "";
    }

    synchronized Map<String,Object> login(String username, String password, String ip) {
        long now = System.currentTimeMillis();
        var window = attempts.compute(ip,(key,old)->old==null||now-old[0]>600_000?new long[]{now,0}:old);
        if (window[1] >= 10) throw new ApiException(429,"登录失败次数过多，请10分钟后重试");
        var rows = db.queryForList("SELECT * FROM users WHERE username=? AND enabled=TRUE",username);
        if (rows.isEmpty() || !encoder.matches(password,String.valueOf(rows.get(0).get("password_hash")))) {
            window[1]++; throw new ApiException(401,"账号或密码错误");
        }
        attempts.remove(ip);
        byte[] bytes = new byte[32]; random.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        db.update("INSERT INTO user_sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",hash(token),rows.get(0).get("id"),Timestamp.from(Instant.now().plusSeconds(43200)));
        return Map.of("token",token);
    }

    void requireAdmin(Map<String,Object> user) {
        if (!"admin".equals(user.get("role"))) throw new ApiException(403,"需要管理员权限");
    }
}
