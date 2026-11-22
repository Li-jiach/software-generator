-- 生产环境完整建表入口，MySQL 8.0+，UTF8MB4。
-- 最新结构版本：2026-11-21 / V007。
-- 本文件只创建缺失结构，不删除现有业务数据；重复执行安全。
-- 升级现有数据库时须另执行 database/migrations/ 中相应的增量脚本。
CREATE DATABASE IF NOT EXISTS copyright_workspace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE copyright_workspace;

CREATE TABLE IF NOT EXISTS schema_versions (
  version VARCHAR(40) PRIMARY KEY,
  description VARCHAR(255) NOT NULL,
  applied_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS users (
  id VARCHAR(36) PRIMARY KEY,
  username VARCHAR(80) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  role VARCHAR(20) NOT NULL,
  department VARCHAR(100) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT chk_user_role CHECK (role IN ('admin','adminDept','research'))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_sessions (
  token_hash CHAR(64) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  expires_at TIMESTAMP(3) NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_session_user FOREIGN KEY (user_id) REFERENCES users(id),
  INDEX idx_session_expiry (expires_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS projects (
  id VARCHAR(40) PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  version VARCHAR(80) NOT NULL,
  department VARCHAR(100) NOT NULL,
  owner VARCHAR(100) NOT NULL,
  description TEXT NOT NULL,
  allowed_roles JSON NOT NULL,
  form_status VARCHAR(20) NOT NULL DEFAULT 'draft',
  form_version INT NOT NULL DEFAULT 1,
  revision INT NOT NULL DEFAULT 1,
  archived BOOLEAN NOT NULL DEFAULT FALSE,
  created_by VARCHAR(36) NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_project_creator FOREIGN KEY (created_by) REFERENCES users(id),
  CONSTRAINT chk_form_status CHECK (form_status IN ('draft','submitted','returned','approved')),
  INDEX idx_project_updated (archived,updated_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS project_fields (
  project_id VARCHAR(40) NOT NULL,
  field_key VARCHAR(80) NOT NULL,
  field_value MEDIUMTEXT NOT NULL,
  updated_by VARCHAR(36) NOT NULL,
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (project_id,field_key),
  CONSTRAINT fk_field_project FOREIGN KEY (project_id) REFERENCES projects(id),
  CONSTRAINT fk_field_user FOREIGN KEY (updated_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS field_reviews (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id VARCHAR(40) NOT NULL,
  field_key VARCHAR(80) NOT NULL,
  field_value_hash CHAR(64) NOT NULL,
  form_version INT NOT NULL,
  status VARCHAR(20) NOT NULL,
  comment TEXT NOT NULL,
  reviewer_id VARCHAR(36) NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_review_project FOREIGN KEY (project_id) REFERENCES projects(id),
  CONSTRAINT fk_review_user FOREIGN KEY (reviewer_id) REFERENCES users(id),
  CONSTRAINT chk_review_status CHECK (status IN ('approved','returned')),
  INDEX idx_review_field (project_id,field_key,id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attachments (
  id VARCHAR(36) PRIMARY KEY,
  project_id VARCHAR(40) NOT NULL,
  name VARCHAR(255) NOT NULL,
  category VARCHAR(80) NOT NULL,
  content_type VARCHAR(150) NOT NULL,
  byte_size BIGINT NOT NULL,
  version INT NOT NULL,
  content_sha256 CHAR(64) NOT NULL,
  content LONGBLOB NULL,
  storage_path VARCHAR(1000) NULL,
  extracted_text MEDIUMTEXT NOT NULL,
  extraction_warning VARCHAR(500) NOT NULL DEFAULT '',
  deleted BOOLEAN NOT NULL DEFAULT FALSE,
  uploaded_by VARCHAR(36) NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_attachment_project FOREIGN KEY (project_id) REFERENCES projects(id),
  CONSTRAINT fk_attachment_user FOREIGN KEY (uploaded_by) REFERENCES users(id),
  UNIQUE KEY uk_attachment_version (project_id,name,version),
  INDEX idx_attachment_project (project_id,deleted,created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS application_records (
  id VARCHAR(36) PRIMARY KEY,
  project_id VARCHAR(40) NOT NULL,
  status VARCHAR(30) NOT NULL,
  reference_no VARCHAR(100) NOT NULL DEFAULT '',
  occurred_at DATETIME NOT NULL,
  note TEXT NOT NULL,
  evidence_id VARCHAR(36) NULL,
  created_by VARCHAR(36) NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_record_project FOREIGN KEY (project_id) REFERENCES projects(id),
  CONSTRAINT fk_record_evidence FOREIGN KEY (evidence_id) REFERENCES attachments(id),
  CONSTRAINT fk_record_user FOREIGN KEY (created_by) REFERENCES users(id),
  INDEX idx_record_project (project_id,occurred_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS activity_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id VARCHAR(40) NOT NULL,
  actor_id VARCHAR(36) NOT NULL,
  title VARCHAR(200) NOT NULL,
  detail MEDIUMTEXT NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_activity_project FOREIGN KEY (project_id) REFERENCES projects(id),
  CONSTRAINT fk_activity_user FOREIGN KEY (actor_id) REFERENCES users(id),
  INDEX idx_activity_project (project_id,id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS knowledge_documents (
  id VARCHAR(36) PRIMARY KEY,
  title VARCHAR(200) NOT NULL,
  source_url VARCHAR(1000) NOT NULL DEFAULT '',
  content MEDIUMTEXT NOT NULL,
  version INT NOT NULL DEFAULT 1,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_by VARCHAR(36) NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_knowledge_user FOREIGN KEY (updated_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  project_id VARCHAR(40) NULL,
  scope VARCHAR(20) NOT NULL,
  role VARCHAR(20) NOT NULL,
  content MEDIUMTEXT NOT NULL,
  sources_json JSON NOT NULL,
  operations_json JSON NULL,
  mode VARCHAR(20) NOT NULL DEFAULT 'model',
  cleared BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_chat_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_chat_project FOREIGN KEY (project_id) REFERENCES projects(id),
  INDEX idx_chat_history (user_id,project_id,scope,cleared,id)
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_versions(version,description) VALUES('V001','项目、分工填报、审核、附件版本、申报记录、知识库、会话与账号');

CREATE TABLE IF NOT EXISTS project_manuals (
  project_id VARCHAR(40) PRIMARY KEY,
  chapters JSON NOT NULL,
  attachment_id VARCHAR(36) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  revision INT NOT NULL DEFAULT 1,
  comment TEXT NOT NULL,
  updated_by VARCHAR(36) NOT NULL,
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  FOREIGN KEY (project_id) REFERENCES projects(id),
  FOREIGN KEY (updated_by) REFERENCES users(id),
  CONSTRAINT fk_project_manual_attachment FOREIGN KEY (attachment_id) REFERENCES attachments(id),
  CHECK (status IN ('draft','submitted','returned','approved'))
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS manual_reviews (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id VARCHAR(40) NOT NULL,
  revision INT NOT NULL,
  chapters JSON NOT NULL,
  attachment_id VARCHAR(36) NULL,
  status VARCHAR(20) NOT NULL,
  comment TEXT NOT NULL,
  reviewer_id VARCHAR(36) NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  FOREIGN KEY (project_id) REFERENCES projects(id),
  FOREIGN KEY (reviewer_id) REFERENCES users(id),
  CONSTRAINT fk_manual_review_attachment FOREIGN KEY (attachment_id) REFERENCES attachments(id)
) ENGINE=InnoDB;
INSERT IGNORE INTO schema_versions(version,description) VALUES('V002','流式附件、手册审核与审核历史');
CREATE TABLE IF NOT EXISTS manual_capture_settings (
  project_id VARCHAR(40) PRIMARY KEY,
  entry_url VARCHAR(500) NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS assistant_reference_fields (
  project_id VARCHAR(40) NOT NULL,
  field_key VARCHAR(80) NOT NULL,
  PRIMARY KEY (project_id,field_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_versions(version,description) VALUES('V003','项目截图入口与助手代填标记');
CREATE TABLE IF NOT EXISTS application_material_reviews (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id VARCHAR(40) NOT NULL,
  kind VARCHAR(20) NOT NULL,
  attachment_id VARCHAR(36) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'submitted',
  comment TEXT NOT NULL,
  submitted_by VARCHAR(36) NOT NULL,
  reviewer_id VARCHAR(36),
  reviewed_at TIMESTAMP(3),
  invalidated BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX (project_id, kind, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (attachment_id) REFERENCES attachments(id) ON DELETE CASCADE,
  FOREIGN KEY (submitted_by) REFERENCES users(id),
  FOREIGN KEY (reviewer_id) REFERENCES users(id),
  CHECK (kind IN ('source', 'ownership')),
  CHECK (status IN ('submitted', 'returned', 'approved'))
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_versions(version,description) VALUES('V004','源程序鉴别材料和权属证明审核');

INSERT IGNORE INTO schema_versions(version,description) VALUES('V005','软著助手会话操作与字段修改记忆');
CREATE TABLE IF NOT EXISTS official_credentials (
  id TINYINT PRIMARY KEY,
  encrypted_credentials BLOB NOT NULL,
  CHECK (id = 1)
) ENGINE=InnoDB;

INSERT IGNORE INTO schema_versions(version,description) VALUES('V006','官网机构账号加密配置');
INSERT IGNORE INTO schema_versions(version,description) VALUES('V007','操作手册最终文件送审');
