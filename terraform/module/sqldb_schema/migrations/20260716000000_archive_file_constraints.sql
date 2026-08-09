-- archive_file constraints decided after the initial schema was applied to dev (GH-81):
-- - fk_archive_file_file_type: match the file_type FKs data_file already has
-- - uk_archive_file_our_s3_url: mirror data_file's uk_summary_s3_url/uk_diff_s3_url; the flat
--   rpki-<ts>.tgz key scheme means a second archive source will need a per-source key prefix
--   (or separate buckets) anyway, so one stored copy per S3 URL is an invariant we can assert
ALTER TABLE archive_file
    ADD CONSTRAINT fk_archive_file_file_type FOREIGN KEY (file_type_id) REFERENCES file_type (id),
    ADD UNIQUE KEY uk_archive_file_our_s3_url (our_s3_url);
