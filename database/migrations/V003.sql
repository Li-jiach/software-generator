USE copyright_workspace;

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
