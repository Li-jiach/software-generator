package cn.copyright.workspace;

import jakarta.servlet.http.*;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
class AuthController {
    final AuthService auth;
    @Value("${app.secure-cookie}") boolean secure;
    AuthController(AuthService auth) { this.auth=auth; }
    @GetMapping("/health") Map<String,Object> health() { auth.db.queryForObject("SELECT 1",Integer.class); return Map.of("status","ok"); }
    @PostMapping("/auth/login") ResponseEntity<?> login(@RequestBody Map<String,String> body,HttpServletRequest req) {
        String username=body.getOrDefault("username",""); String password=body.getOrDefault("password","");
        if(username.length()>80||password.length()>200) throw new ApiException(400,"账号或密码过长");
        String token=(String)auth.login(username,password,req.getRemoteAddr()).get("token");
        var cookie=ResponseCookie.from("COPYRIGHT_SESSION",token).httpOnly(true).secure(secure).sameSite("Strict").path("/api").maxAge(43200).build();
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE,cookie.toString()).body(Map.of("ok",true));
    }
    @GetMapping("/auth/me") Map<String,Object> me(HttpServletRequest req) { return auth.current(req); }
    @PostMapping("/auth/logout") ResponseEntity<?> logout(HttpServletRequest req) {
        auth.db.update("DELETE FROM user_sessions WHERE token_hash=?",AuthService.hash(auth.cookie(req)));
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE,ResponseCookie.from("COPYRIGHT_SESSION","").path("/api").httpOnly(true).sameSite("Strict").maxAge(0).build().toString()).body(Map.of("ok",true));
    }
}
