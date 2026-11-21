package cn.copyright.workspace;

import com.fasterxml.jackson.core.type.TypeReference;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
class OfficialCredentials {
    private static final int NONCE_SIZE = 12;
    private final SecureRandom random = new SecureRandom();
    private final ProjectService projects;
    private final String encodedKey;

    OfficialCredentials(ProjectService projects, @Value("${OFFICIAL_CREDENTIAL_KEY:}") String encodedKey) {
        this.projects = projects;
        this.encodedKey = encodedKey;
    }

    Map<String,String> read() {
        var rows = projects.db().queryForList("SELECT encrypted_credentials FROM official_credentials WHERE id=1", byte[].class);
        if (rows.isEmpty()) return Map.of();
        var buffer = ByteBuffer.wrap(rows.get(0));
        byte[] nonce = new byte[NONCE_SIZE];
        buffer.get(nonce);
        byte[] ciphertext = new byte[buffer.remaining()];
        buffer.get(ciphertext);
        try {
            byte[] plaintext = cipher(Cipher.DECRYPT_MODE, nonce).doFinal(ciphertext);
            return projects.decode(new String(plaintext, StandardCharsets.UTF_8), new TypeReference<Map<String,String>>(){});
        } catch (GeneralSecurityException e) {
            throw new ApiException(503, "官网账号解密失败，请检查服务端加密密钥");
        }
    }

    void save(Map<String,Object> body) {
        String username = ProjectService.required(body, "username", 200);
        if (!(body.get("password") instanceof String password) || password.isBlank() || password.length() > 256)
            throw new ApiException(400, "请输入有效的官网密码");
        byte[] nonce = new byte[NONCE_SIZE];
        random.nextBytes(nonce);
        try {
            String json = projects.encode(Map.of("username", username, "password", password));
            byte[] ciphertext = cipher(Cipher.ENCRYPT_MODE, nonce).doFinal(json.getBytes(StandardCharsets.UTF_8));
            byte[] stored = ByteBuffer.allocate(nonce.length + ciphertext.length).put(nonce).put(ciphertext).array();
            projects.db().update("""
                INSERT INTO official_credentials(id,encrypted_credentials) VALUES(1,?)
                ON DUPLICATE KEY UPDATE encrypted_credentials=VALUES(encrypted_credentials)
                """, stored);
        } catch (GeneralSecurityException e) {
            throw new ApiException(503, "官网账号加密失败");
        }
    }

    private Cipher cipher(int mode, byte[] nonce) throws GeneralSecurityException {
        byte[] key;
        try {
            key = Base64.getDecoder().decode(encodedKey);
        } catch (IllegalArgumentException e) {
            throw new ApiException(503, "服务端官网账号加密密钥无效");
        }
        if (key.length != 32) throw new ApiException(503, "服务端须配置官网账号加密密钥");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(mode, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, nonce));
        return cipher;
    }
}
