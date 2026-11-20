USE copyright_workspace;

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
