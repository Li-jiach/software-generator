USE copyright_workspace;
ALTER TABLE project_manuals
  ADD COLUMN attachment_id VARCHAR(36) NULL,
  ADD CONSTRAINT fk_project_manual_attachment FOREIGN KEY (attachment_id) REFERENCES attachments(id);
ALTER TABLE manual_reviews
  ADD COLUMN attachment_id VARCHAR(36) NULL,
  ADD CONSTRAINT fk_manual_review_attachment FOREIGN KEY (attachment_id) REFERENCES attachments(id);
INSERT IGNORE INTO schema_versions(version,description) VALUES('V007','操作手册最终文件送审');
