from datetime import datetime, timezone
from pathlib import Path
import re
from typing import TYPE_CHECKING

import dateutil.parser

from rpkilog.data_file_source import DataFileSource
from rpkilog.data_file_super import DataFileSuper
from rpkilog.data_file_type import DataFileType
from rpkilog.local_storage_type import LocalStorageType

if TYPE_CHECKING:
    import mariadb
    from types_boto3_s3.service_resource import ObjectSummary


class SnapshotSummaryFile(DataFileSuper):
    """
    Represents an rpkiclient snapshot-summary file: YYYYMMDDTHHMMSSZ.json[.bz2]

    These are produced by rpkilog-rpkiclient-uploader and stored in the snapshot-summary S3 bucket.
    """
    default_filename_strftime_expression = '%Y%m%dT%H%M%SZ.json'
    # minimum uncompressed byte size of a valid rpkiclient output JSON
    MINIMUM_SIZE = 8_500_000
    sql_file_type_name = 'rpkiclient_snapshot_summary_v1'
    json_read_cache_populate_methods = DataFileSuper.json_read_cache_populate_methods + [
        '_cache_buildmachine',
        '_cache_observation_datetime',
    ]
    s3_last_modified: datetime = None
    source: DataFileSource = None

    @classmethod
    def infer_datetimestamp_from_path(cls, path) -> datetime:
        """Extract datetime from a snapshot-summary filename; rejects diff filenames."""
        rem = re.search(r'(?P<dt>\d{8}T\d{4,6}Z)\.json(\.bz2)?$', str(path.name))
        if not rem:
            raise ValueError(f'regex did not match a snapshot-summary filename in given path: {path}')
        dt = dateutil.parser.parse(rem.group('dt'))
        retval = dt.replace(tzinfo=timezone.utc)
        return retval

    @classmethod
    def datetimestamp_from_json(cls, json_data: dict) -> datetime:
        """
        Extract the buildtime datetime from rpkiclient metadata; the result is always tz-aware
        UTC.  A buildtime with no timezone indicator is assumed UTC; one carrying an offset is
        converted.
        """
        dt = dateutil.parser.parse(json_data['metadata']['buildtime'])
        if dt.tzinfo is None:
            retval = dt.replace(tzinfo=timezone.utc)
        else:
            retval = dt.astimezone(timezone.utc)
        return retval

    @classmethod
    def from_s3_object_summary(cls, obj: 'ObjectSummary') -> 'SnapshotSummaryFile':
        """
        Instantiate from an S3 ObjectSummary: UNCACHED, with s3_url pointing at the listed object
        and datetimestamp taken from the object key.

        source is left None (a bare listing doesn't identify it), and observation_datetime is not
        populated: the key's timestamp may differ from the authoritative JSON metadata.buildtime
        by a few seconds, and the observation_datetime property reads the latter.
        """
        datetimestamp = cls.infer_datetimestamp_from_path(Path(obj.key))
        retval = cls(
            datetimestamp=datetimestamp,
            local_storage_type=LocalStorageType.UNCACHED,
            s3_url=f's3://{obj.bucket_name}/{obj.key}',
            s3_stored=True,
        )
        retval.s3_last_modified = obj.last_modified
        return retval

    @property
    def buildmachine(self) -> str:
        """
        The metadata.buildmachine hostname read from the JSON content; matched against
        BuildMachineToSourceMapping regexes to identify this file's `source`.  Cached under
        _metadata_cache['buildmachine'] on first read via json_data_populate_cache() so later
        accesses don't re-read the file.
        """
        if 'buildmachine' not in self._metadata_cache:
            self.json_data_populate_cache()
        retstr = self._metadata_cache['buildmachine']
        return retstr

    def _cache_buildmachine(self, data: bytes, json_data: dict):
        """Populate the buildmachine cache; invoked via json_read_cache_populate_methods."""
        self._metadata_cache['buildmachine'] = json_data['metadata']['buildmachine']

    @property
    def observation_datetime(self) -> datetime:
        """
        The authoritative buildtime read from the JSON metadata; always tz-aware UTC.  Cached
        under _metadata_cache['observation_datetime'] on first read via
        json_data_populate_cache() so later accesses don't re-read the file.
        """
        if 'observation_datetime' not in self._metadata_cache:
            self.json_data_populate_cache()
        retval = self._metadata_cache['observation_datetime']
        return retval

    def _cache_observation_datetime(self, data: bytes, json_data: dict):
        """Populate the observation_datetime cache; invoked via json_read_cache_populate_methods."""
        self._metadata_cache['observation_datetime'] = self.datetimestamp_from_json(json_data)

    @property
    def source_id(self) -> int | None:
        """
        The data_file.source_id FK value, read from self.source; None while the source is unknown.
        """
        if self.source is not None:
            retval = self.source.id
        else:
            retval = None
        return retval

    def db_row_exists(self, db: 'mariadb.SyncConnection') -> bool:
        """
        Return True if the data_file table already has a row for this file.

        A known self.s3_url is checked against summary_s3_url — cheap, no download needed.
        Otherwise check by primary key (source_id, observation_datetime); accessing
        observation_datetime downloads the file from S3 when uncached.
        """
        cursor = db.cursor()
        try:
            if self.s3_url is not None:
                cursor.execute(
                    'SELECT 1 FROM data_file WHERE summary_s3_url = ?',
                    (self.s3_url,),
                )
            elif self.source_id is not None:
                # data_file.observation_datetime is a tz-less DATETIME column storing UTC
                cursor.execute(
                    'SELECT 1 FROM data_file WHERE source_id = ? AND observation_datetime = ?',
                    (self.source_id, self.observation_datetime.replace(tzinfo=None)),
                )
            else:
                raise ValueError(f'cannot query data_file without s3_url or source_id: {self}')
            row = cursor.fetchone()
        finally:
            cursor.close()
        retval = row is not None
        return retval

    def db_insert(self, db: 'mariadb.SyncConnection', summary_file_type: DataFileType):
        """
        INSERT a data_file row for this summary file, populating the summary_* columns.
        self.source must be known; raise ValueError when it is None.
        """
        if self.source_id is None:
            raise ValueError(f'cannot INSERT data_file row without a known source: {self}')
        if self.s3_last_modified is not None:
            stored_datetime = self.s3_last_modified.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            stored_datetime = None
        columns = [
            'source_id',
            'observation_datetime',
            'summary_s3_url',
            'summary_size_bytes',
            'summary_sha256',
            'summary_file_type_id',
            'summary_stored_datetime',
        ]
        values = (
            self.source_id,
            self.observation_datetime.replace(tzinfo=None),
            self.s3_url,
            self.size_bytes_uncompressed(),
            self.sha256_digest(),
            summary_file_type.id,
            stored_datetime,
        )
        placeholders = ', '.join(['?'] * len(columns))
        statement = f'INSERT INTO data_file ({", ".join(columns)}) VALUES ({placeholders})'
        cursor = db.cursor()
        try:
            cursor.execute(statement, values)
        finally:
            cursor.close()

    def validate_size(self):
        """
        Raise RuntimeError if the uncompressed data is below MINIMUM_SIZE bytes.

        Validation is only meaningful on a locally-cached file (e.g. before an upload); raise
        ValueError rather than downloading when there is none.
        """
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED | LocalStorageType.BZIP2:
                size = self.size_bytes_uncompressed()
            case _:
                raise ValueError(f'cannot validate size without a locally-cached file: {self}')
        if size < self.MINIMUM_SIZE:
            raise RuntimeError(f'file too small ({size} bytes < {self.MINIMUM_SIZE}): {self}')
