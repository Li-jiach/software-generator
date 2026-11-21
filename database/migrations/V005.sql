USE copyright_workspace;
-- 在 schema_versions 中尚未记录 V005 时执行一次。
ALTER TABLE chat_messages ADD COLUMN operations_json JSON NULL AFTER sources_json;
INSERT IGNORE INTO schema_versions(version,description) VALUES('V005','软著助手会话操作与字段修改记忆');
