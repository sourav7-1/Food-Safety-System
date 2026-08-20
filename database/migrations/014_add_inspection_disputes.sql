-- Apply this migration to an existing database created before vendors
-- could dispute an inspection report. Fresh installations already include
-- these tables through database/schema.sql.
--
-- Lets a vendor flag a mismatch on one of their inspection reports (with
-- optional image/video/audio/document proof) and an administrator review
-- and resolve that dispute.

USE smart_street_food_safety;

CREATE TABLE IF NOT EXISTS inspection_disputes (
  dispute_id INT NOT NULL AUTO_INCREMENT,
  inspection_id INT NOT NULL,
  vendor_id INT NOT NULL,
  reason TEXT NOT NULL,
  status ENUM('submitted', 'under_review', 'resolved', 'rejected') NOT NULL DEFAULT 'submitted',
  submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TIMESTAMP NULL,
  admin_response TEXT NULL,
  PRIMARY KEY (dispute_id),
  CONSTRAINT chk_inspection_disputes_reason_not_blank CHECK (CHAR_LENGTH(TRIM(reason)) > 0),
  CONSTRAINT fk_inspection_disputes_inspection_id
    FOREIGN KEY (inspection_id) REFERENCES inspections (inspection_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT fk_inspection_disputes_vendor_id
    FOREIGN KEY (vendor_id) REFERENCES vendors (vendor_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_inspection_disputes_inspection_id ON inspection_disputes (inspection_id);
CREATE INDEX idx_inspection_disputes_vendor_id ON inspection_disputes (vendor_id);
CREATE INDEX idx_inspection_disputes_status ON inspection_disputes (status);
CREATE INDEX idx_inspection_disputes_submitted_at ON inspection_disputes (submitted_at);

CREATE TABLE IF NOT EXISTS inspection_dispute_evidence (
  evidence_id INT NOT NULL AUTO_INCREMENT,
  dispute_id INT NOT NULL,
  uploaded_by INT NULL,
  file_name VARCHAR(255) NOT NULL,
  stored_file_name VARCHAR(255) NOT NULL,
  file_type ENUM('image', 'video', 'audio', 'document') NOT NULL,
  mime_type VARCHAR(150) NOT NULL,
  file_size INT UNSIGNED NOT NULL,
  storage_path VARCHAR(500) NOT NULL,
  file_hash CHAR(64) NOT NULL,
  uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (evidence_id),
  CONSTRAINT chk_inspection_dispute_evidence_file_name_not_blank CHECK (CHAR_LENGTH(TRIM(file_name)) > 0),
  CONSTRAINT chk_inspection_dispute_evidence_file_size_positive CHECK (file_size > 0),
  CONSTRAINT chk_inspection_dispute_evidence_file_hash_length CHECK (CHAR_LENGTH(file_hash) = 64),
  CONSTRAINT fk_inspection_dispute_evidence_dispute_id
    FOREIGN KEY (dispute_id) REFERENCES inspection_disputes (dispute_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT fk_inspection_dispute_evidence_uploaded_by
    FOREIGN KEY (uploaded_by) REFERENCES users (user_id)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX idx_inspection_dispute_evidence_dispute_id ON inspection_dispute_evidence (dispute_id);
