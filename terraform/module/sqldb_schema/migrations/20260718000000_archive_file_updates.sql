-- archive_file updates (GH-81), batched into one follow-up apply to dev:
--
-- 1) filename_derived_datetime: the timestamp INFERRED from the rpki-<ts>.tgz filename inside
--    source_url, materialized so range scans and backlog ordering can be indexed (the value is
--    otherwise only reachable by regex over a VARCHAR).  Known at discovery; approximate.
--    observation_datetime (read from file contents at ingest) remains authoritative.
-- 2) comment-only clarification of our_size_bytes / our_sha256: snapshot TARs are stored
--    byte-for-byte as published (.tgz), never re-compressed, so size and sha256 describe the
--    published file itself -- comparable to upstream checksums -- not a decompressed stream.
--    MODIFY restates the column definitions unchanged apart from the COMMENT.
ALTER TABLE archive_file
    ADD COLUMN filename_derived_datetime DATETIME NULL
        COMMENT 'UTC; INFERRED from the filename timestamp in source_url; known at discovery. Approximate -- observation_datetime (from file contents, at ingest) is authoritative'
        AFTER source_url,
    ADD KEY k_archive_file_filename_derived (source_id, filename_derived_datetime),
    MODIFY our_size_bytes BIGINT UNSIGNED NULL COMMENT 'size in bytes of the archive file as published (the .tgz itself; stored byte-for-byte, never re-compressed)',
    MODIFY our_sha256 BINARY(32) NULL COMMENT 'sha256 of the archive file as published (the .tgz bytes), comparable to upstream checksums';
