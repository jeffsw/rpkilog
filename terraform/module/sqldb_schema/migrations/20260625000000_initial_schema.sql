CREATE TABLE source (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name        VARCHAR(255)  NOT NULL,
    base_url    VARCHAR(1024) NULL COMMENT 'base URL for crawled sources; NULL for our own uploaders',
    active      BOOL         NOT NULL DEFAULT TRUE,
    notes       TEXT         NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_source_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO source (name, base_url, notes) VALUES
    ('rpkiclient.rpkilog.com', NULL, 'uploads from our production rpki-client instance'),
    ('josephine.sobornost.net', 'https://josephine.sobornost.net/rpkidata/', 'historic rpki-client snapshots');

-- file_type: a (kind, version) lookup describing the format of each underlying file.  A new format
-- revision allows determining compatibility and whether older files have been reprocessed after updates.
CREATE TABLE file_type (
    id            INT UNSIGNED                  NOT NULL AUTO_INCREMENT,
    kind          ENUM('full','summary','diff') NOT NULL,
    name          VARCHAR(255)                  NOT NULL COMMENT 'versioned format id, e.g. rpkilog_diff_v2',
    description   TEXT                          NULL,
    deprecated_at DATETIME                      NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_file_type_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO file_type (kind, name, description) VALUES
    ('full',    'rpkiclient_snapshot_full_v1',    'rpki-client tar/json full snapshot'),
    ('summary', 'rpkiclient_snapshot_summary_v1', 'rpki-client JSON metadata + roas array'),
    ('diff',    'rpkilog_diff_v1',    'rpkilog_vrp_cache_diff_set; vrp diff vs ancestor');

CREATE TABLE data_file (
    source_id               INT UNSIGNED    NOT NULL,
    observation_datetime    DATETIME        NOT NULL COMMENT 'UTC; metadata.buildtime (NOT the source filename timestamp)',
    summary_s3_url          VARCHAR(1024)   NULL,
    summary_size_bytes      BIGINT UNSIGNED NULL COMMENT 'uncompressed size in bytes, even when stored compressed',
    summary_sha256          BINARY(32)      NULL COMMENT 'uncompressed sha256',
    summary_file_type_id    INT UNSIGNED    NULL,
    summary_stored_datetime DATETIME        NULL COMMENT 'when the summary file landed in our S3 bucket',
    diff_s3_url             VARCHAR(1024)   NULL,
    diff_size_bytes         BIGINT UNSIGNED NULL COMMENT 'uncompressed size in bytes, even when stored compressed',
    diff_sha256             BINARY(32)      NULL COMMENT 'uncompressed sha256',
    diff_file_type_id       INT UNSIGNED    NULL,
    diff_stored_datetime    DATETIME        NULL COMMENT 'when the diff file landed in our S3 bucket (i.e. diff processing completed)',
    -- A diff is computed between a pair of data_file: this row and a previous row.
    diff_previous_source_id            INT UNSIGNED NULL COMMENT 'source_id of the "previous" data_file this diff was computed against; with diff_previous_observation_datetime identifies that row; NULL until known',
    diff_previous_observation_datetime DATETIME     NULL COMMENT 'observation_datetime (authoritative buildtime) of the "previous" data_file; see diff_previous_source_id',
    PRIMARY KEY (source_id, observation_datetime),
    UNIQUE KEY uk_summary_s3_url (summary_s3_url),
    UNIQUE KEY uk_diff_s3_url (diff_s3_url),
    KEY k_observation_datetime (observation_datetime),
    CONSTRAINT fk_data_file_source FOREIGN KEY (source_id) REFERENCES source (id),
    CONSTRAINT fk_data_file_summary_file_type FOREIGN KEY (summary_file_type_id) REFERENCES file_type (id),
    CONSTRAINT fk_data_file_diff_file_type FOREIGN KEY (diff_file_type_id) REFERENCES file_type (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 WITH SYSTEM VERSIONING;

CREATE TABLE archive_file (
    source_id            INT UNSIGNED    NOT NULL,
    source_url           VARCHAR(512)    NOT NULL COMMENT 'URL the file was discovered at; stable per-file identity within a source (the PK; crawler dedups on this). 512 keeps (source_id, source_url) under the 3072-byte InnoDB index limit',
    discovered_datetime  DATETIME        NOT NULL COMMENT 'when the crawler first listed this file',
    file_type_id         INT UNSIGNED    NULL COMMENT 'if known, the type of file',
    our_s3_url           VARCHAR(1024)   NULL COMMENT 'S3 URL of our stored copy of the downloaded archive file; NULL until downloaded or upon deletion',
    our_size_bytes       BIGINT UNSIGNED NULL COMMENT 'uncompressed size in bytes of the archive file, even when stored bzip2-compressed',
    our_sha256           BINARY(32)      NULL COMMENT 'sha256 of the (uncompressed) archive file content',
    our_stored_datetime  DATETIME        NULL COMMENT 'when our copy of the archive file landed in our S3 bucket',
    observation_datetime DATETIME        NULL COMMENT 'UTC; the snapshot buildtime read from the file CONTENTS during processing',
    PRIMARY KEY (source_id, source_url),
    KEY k_archive_file_observation (source_id, observation_datetime),
    CONSTRAINT fk_archive_file_source FOREIGN KEY (source_id) REFERENCES source (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
