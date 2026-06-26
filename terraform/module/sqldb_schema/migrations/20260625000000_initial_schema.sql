-- Initial snapshot-tracking schema (GH-81).
--
-- This file is the single source of truth for the intended database structure.  It is applied
-- by Atlas Community Edition via the `atlas migrate apply` CLI (versioned-migrations workflow),
-- invoked from the sqldb_schema Terraform module: Atlas executes these statements verbatim and
-- records the applied version in its atlas_schema_revisions table.  Hand-written on purpose --
-- Atlas cannot model MariaDB
-- `WITH SYSTEM VERSIONING`, so `migrate diff` is unusable and atlas.sum is maintained with
-- `atlas migrate hash`.

-- source: one row per place data files come from, e.g. our own rpki-client uploader and the
-- josephine.sobornost.net archive.
CREATE TABLE source (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    name        VARCHAR(255)  NOT NULL,
    url         VARCHAR(255) NULL COMMENT 'base URL for crawled sources; NULL for our own uploaders',
    active      BOOL         NOT NULL DEFAULT TRUE,
    notes       TEXT         NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_source_name (name)
);

-- file_type: a (kind, version) lookup describing the format of each underlying file.  A new
-- format revision is one INSERT, never an ALTER TABLE on data_file.  deprecated_at marks a
-- format retired; combined with the per-file references on data_file it answers both "which
-- files still use an old format?" and "is this format safe to drop?".
CREATE TABLE file_type (
    id            INT UNSIGNED                  NOT NULL AUTO_INCREMENT,
    kind          ENUM('full','summary','diff') NOT NULL,
    name          VARCHAR(255)                  NOT NULL COMMENT 'versioned format id, e.g. rpkilog_diff_v2',
    description   TEXT                          NULL,
    deprecated_at DATETIME                      NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_file_type_name (name)
);

INSERT INTO file_type (kind, name, description) VALUES
    ('full',    'rpkiclient_snapshot_full_v1',    'rpki-client tar/json full snapshot'),
    ('summary', 'rpkiclient_snapshot_summary_v1', 'rpki-client JSON metadata + roas array'),
    ('diff',    'rpkilog_diff_v1',    'rpkilog_vrp_cache_diff_set; vrp diff vs ancestor');

-- data_file: one row per rpki_snapshot, per source.  Column groups prefixed full_/summary_/diff_
-- describe the underlying files rpki_snapshot_full, rpki_snapshot_summary, rpki_snapshot_diff.
-- A NULL *_s3_url means that underlying file doesn't exist (yet).  *_size_bytes is the
-- UNCOMPRESSED size even when stored bzip2-compressed.  *_stored_datetime records when that
-- file landed in our S3 bucket (diff_stored_datetime doubles as "diff processing completed").
-- SYSTEM VERSIONING preserves the history of the status columns without a separate audit table.
CREATE TABLE data_file (
    source_id               INT UNSIGNED    NOT NULL,
    observation_datetime    DATETIME        NOT NULL COMMENT 'UTC; the YYYYMMDDTHHMMSSZ key timestamp',
    full_source_url         VARCHAR(1024)   NULL COMMENT 'original URL we fetched the full file from; NULL for our own uploads',
    full_s3_url             VARCHAR(1024)   NULL,
    full_size_bytes         BIGINT UNSIGNED NULL COMMENT 'uncompressed size in bytes, even when stored bzip2-compressed',
    full_sha256             BINARY(32)      NULL,
    full_file_type_id       INT UNSIGNED    NULL,
    full_stored_datetime    DATETIME        NULL COMMENT 'when the full file landed in our S3 bucket',
    summary_source_url      VARCHAR(1024)   NULL COMMENT 'original URL we fetched the summary file from; NULL for our own uploads',
    summary_s3_url          VARCHAR(1024)   NULL,
    summary_size_bytes      BIGINT UNSIGNED NULL COMMENT 'uncompressed size in bytes, even when stored bzip2-compressed',
    summary_sha256          BINARY(32)      NULL,
    summary_file_type_id    INT UNSIGNED    NULL,
    summary_stored_datetime DATETIME        NULL COMMENT 'when the summary file landed in our S3 bucket',
    diff_s3_url             VARCHAR(1024)   NULL,
    diff_size_bytes         BIGINT UNSIGNED NULL COMMENT 'uncompressed size in bytes, even when stored bzip2-compressed',
    diff_sha256             BINARY(32)      NULL,
    diff_file_type_id       INT UNSIGNED    NULL,
    diff_stored_datetime    DATETIME        NULL COMMENT 'when the diff file landed in our S3 bucket (i.e. diff processing completed)',
    discovered_datetime     DATETIME        NULL COMMENT 'when we learned the file exists (crawler listing or upload)',
    PRIMARY KEY (source_id, observation_datetime),
    KEY k_observation_datetime (observation_datetime),
    CONSTRAINT fk_data_file_source FOREIGN KEY (source_id) REFERENCES source (id),
    CONSTRAINT fk_data_file_full_file_type FOREIGN KEY (full_file_type_id) REFERENCES file_type (id),
    CONSTRAINT fk_data_file_summary_file_type FOREIGN KEY (summary_file_type_id) REFERENCES file_type (id),
    CONSTRAINT fk_data_file_diff_file_type FOREIGN KEY (diff_file_type_id) REFERENCES file_type (id)
) WITH SYSTEM VERSIONING;
