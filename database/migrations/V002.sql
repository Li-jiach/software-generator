USE copyright_workspace;
-- 仅在V002尚未应用的现有数据库执行一次。
ALTER TABLE attachments MODIFY content LONGBLOB NULL, ADD COLUMN storage_path VARCHAR(1000) NULL;
CREATE TABLE IF NOT EXISTS project_manuals (
  project_id VARCHAR(40) PRIMARY KEY,
  chapters JSON NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  revision INT NOT NULL DEFAULT 1,
  comment TEXT NOT NULL,
  updated_by VARCHAR(36) NOT NULL,
  updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  FOREIGN KEY (project_id) REFERENCES projects(id),
  FOREIGN KEY (updated_by) REFERENCES users(id),
  CHECK (status IN ('draft','submitted','returned','approved'))
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS manual_reviews (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id VARCHAR(40) NOT NULL,
  revision INT NOT NULL,
  chapters JSON NOT NULL,
  status VARCHAR(20) NOT NULL,
  comment TEXT NOT NULL,
  reviewer_id VARCHAR(36) NOT NULL,
  created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  FOREIGN KEY (project_id) REFERENCES projects(id),
  FOREIGN KEY (reviewer_id) REFERENCES users(id)
) ENGINE=InnoDB;
INSERT IGNORE INTO schema_versions(version,description) VALUES('V002','流式附件、手册审核与审核历史');
