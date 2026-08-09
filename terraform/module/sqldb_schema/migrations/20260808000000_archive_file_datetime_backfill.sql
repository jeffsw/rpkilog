-- Backfill filename_derived_datetime (added in 20260718000000_archive_file_updates) for rows
-- inserted before that column existed.  Nothing else ever updates the column on existing rows,
-- and NULL values are excluded by every bounded db_select_within_range scan, so without this
-- backfill pre-column rows silently escape bounded backlog/reconcile runs forever.
UPDATE archive_file
    SET filename_derived_datetime = STR_TO_DATE(
        REGEXP_SUBSTR(source_url, '[0-9]{8}T[0-9]{6}Z'),
        '%Y%m%dT%H%i%sZ'
    )
    WHERE filename_derived_datetime IS NULL
      AND source_url REGEXP '[0-9]{8}T[0-9]{6}Z';
