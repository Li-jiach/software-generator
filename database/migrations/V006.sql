USE copyright_workspace;
CREATE TABLE IF NOT EXISTS official_credentials (
  id TINYINT PRIMARY KEY,
  encrypted_credentials BLOB NOT NULL,
  CHECK (id = 1)
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_versions(version,description) VALUES('V006','官网机构账号加密配置');
