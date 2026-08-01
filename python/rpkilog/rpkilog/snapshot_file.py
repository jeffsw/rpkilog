"""
SnapshotFile: represents an RPKI archive snapshot TAR (rpki-YYYYMMDDTHHMMSSZ.tgz).

A "snapshot" is the gzipped TAR published by an upstream RPKI archive site and re-hosted by rpkilog in
the snapshot S3 bucket.  Each snapshot TAR contains, among other things, the rpki-client output JSON
that we extract into a SnapshotSummaryFile.  This class is the planned home for the snapshot-TAR
*file* concerns currently scattered through archive_site_crawler.py: filename/datetime derivation,
validating the TAR, extracting the summary, and uploading the TAR to S3.

STATUS: implemented.  A snapshot's cached bytes are an opaque gzipped TAR
(LocalStorageType.SNAPSHOT_TGZ) held at local_filepath_tgz.  Operations that only make sense for a
JSON document raise (see the type-invalid overrides below), the S3 round-trip moves the TAR
byte-for-byte under its '.tgz' key, local-cache cleanup unlinks the TAR, validate_tar() checks the
archive is readable, and extract_summary_file() pulls the rpki-client JSON out as a
SnapshotSummaryFile.  archive_site_crawler is rebased onto this class.

Design notes:
  - SnapshotFile does NOT acquire bytes from, or parse the URLs of, the archive site.  Acquisition
    (transport, auth, headers, timeouts, retry/backoff, mirror failover) varies per archive and is
    owned by the crawler (and a possible future ArchiveSite abstraction), which downloads to a temp
    path and then points a SnapshotFile at it (local_filepath_tgz + SNAPSHOT_TGZ).  This is why
    s3_download() lives here (rehydrating from rpkilog's own canonical store, one transport) but no
    archive-download method does.  source_url is kept purely as provenance metadata.
  - Cache *state* is modeled by LocalStorageType; "operation invalid for this file *type*" is a
    type-level override here.  The two are orthogonal: DataFileSuper's match statements all carry a
    `case _: raise` default as a safety net for an unhandled state, while the JSON-only operations
    below raise regardless of state because a snapshot TAR is simply not a JSON document.
  - The inherited local_filepath_uncompressed / local_filepath_bz2 properties are overridden to
    raise; a snapshot has no uncompressed-JSON or bz2 form.  repr_attrs is redefined accordingly so
    __repr__ (used in error messages) does not trip those raises.

SQL: a SnapshotFile maps to one `archive_file` row, keyed by the (source_id, source_url) PK.  The
  db_* methods below cover the row's lifecycle — insert at discovery, update when our S3 copy is
  stored, update at ingest (observation_datetime, whose non-NULL state is the ingested marker) —
  and from_db_row() / db_select_within_range() construct UNCACHED instances from rows with explicit
  s3_url + source_url, so the process-global default S3 base URL is never consulted.  This mirrors
  SnapshotSummaryFile's methods against `data_file`: row CRUD lives on each file class.

TODO: the upload path reads the full TAR (100MB-1GB) three times per snapshot: s3_upload() streams
  it to S3, then db_update_our_copy() calls size_bytes_uncompressed() and sha256_digest(), each of
  which makes its own complete pass via _iter_uncompressed_chunks() because the metadata cache is
  empty at that point.  These reads could be consolidated.
"""
import logging
import os
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import TYPE_CHECKING
import urllib.parse

import boto3
import dateutil.parser

from rpkilog.data_file_source import DataFileSource
from rpkilog.data_file_super import DataFileSuper
from rpkilog.data_file_type import DataFileType
from rpkilog.local_storage_type import LocalStorageType
from rpkilog.snapshot_summary_file import SnapshotSummaryFile

if TYPE_CHECKING:
    import mariadb

logger = logging.getLogger(__name__)


class SnapshotFile(DataFileSuper):
    """
    Represents an RPKI archive snapshot TAR: rpki-YYYYMMDDTHHMMSSZ.tgz

    Published by an upstream RPKI archive site and re-hosted by rpkilog in the snapshot S3 bucket.
    See the module docstring for design notes and outstanding TODOs.
    """
    default_filename_strftime_expression = 'rpki-%Y%m%dT%H%M%SZ.tgz'
    # __repr__ iterates repr_attrs via getattr(self, name, None), which only swallows AttributeError;
    # the inherited local_filepath_uncompressed/_bz2 raise on a SnapshotFile, so they are dropped
    # here in favor of local_filepath_tgz (and source_url is added).
    repr_attrs = [
        'datetimestamp',
        'local_filepath_tgz',
        'local_storage_type',
        's3_url',
        's3_stored',
        'source_url',
    ]

    # Regex matching the rpki-client summary JSON member inside a snapshot TAR, e.g.
    # 'rpki-20211121T000709Z/output/rpki-client.json'.  Used by extract_summary_file().
    summary_member_re = r'^rpki-(\d{8}T\d{6}Z)/output/rpki-client\.json$'
    sql_file_type_name = 'rpkiclient_snapshot_full_v1'
    source: DataFileSource = None
    # archive_file DATETIME column mirrors, hydrated (tz-aware UTC) by from_db_row(); None until
    # loaded from, or recorded to, the database
    discovered_datetime: datetime = None
    observation_datetime: datetime = None

    def __init__(self, *args, source_url: str | None = None, local_filepath_tgz: Path | None = None,
                 **kwargs):
        """
        Add source_url and local_filepath_tgz on top of the DataFileSuper constructor.

        source_url is the archive-site HTTP URL this snapshot originated from, recorded purely as
        provenance metadata (logging + a planned column in the SQL files table); SnapshotFile never
        fetches it.  It is None for snapshots discovered via S3 listing or loaded from SQL.

        local_filepath_tgz is the locally-cached '.tgz' path; when None it defaults (via the property
        below) to local_storage_dir / default_filename.
        """
        super().__init__(*args, **kwargs)
        self.source_url = source_url
        self.local_filepath_tgz = local_filepath_tgz

    @classmethod
    def infer_datetimestamp_from_path(cls, path) -> datetime:
        """Extract datetime from a snapshot TAR filename; rejects summary and vrpdiff filenames."""
        rem = re.search(r'rpki-(?P<dt>\d{8}T\d{6}Z)\.tgz$', str(path.name))
        if not rem:
            raise ValueError(f'regex did not match a snapshot TAR filename in given path: {path}')
        dt = dateutil.parser.parse(rem.group('dt'))
        retval = dt.replace(tzinfo=timezone.utc)
        return retval

    # --- local-file path representation ---------------------------------------------------------

    @property
    def local_filepath_tgz(self) -> Path:
        if self._local_filepath_tgz:
            return self._local_filepath_tgz
        retpath = Path(self.local_storage_dir, self.default_filename)
        return retpath

    @local_filepath_tgz.setter
    def local_filepath_tgz(self, value: Path):
        self._local_filepath_tgz = value

    @property
    def local_filepath_uncompressed(self) -> Path:
        raise TypeError('a snapshot TAR has no uncompressed-JSON form; use local_filepath_tgz')

    @local_filepath_uncompressed.setter
    def local_filepath_uncompressed(self, value: Path):
        # DataFileSuper.__init__ assigns None here; reject any real JSON path on a SnapshotFile.
        if value is not None:
            raise TypeError('a snapshot TAR has no uncompressed-JSON form; use local_filepath_tgz')

    @property
    def local_filepath_bz2(self) -> Path:
        raise TypeError('a snapshot TAR has no bz2 form; use local_filepath_tgz')

    @local_filepath_bz2.setter
    def local_filepath_bz2(self, value: Path):
        # DataFileSuper.__init__ assigns None here; reject any real bz2 path on a SnapshotFile.
        if value is not None:
            raise TypeError('a snapshot TAR has no bz2 form; use local_filepath_tgz')

    # --- S3 (move the TAR byte-for-byte; no bz2 recompression, no '.bz2' suffix) -----------------

    def s3_url_set_to_default(self):
        """
        Override of DataFileSuper.s3_url_set_to_default(), which appends '.bz2'.

        A snapshot's S3 key is its '.tgz' filename as-is, so derive 's3://<base>/rpki-...Z.tgz' with
        no suffix.  Sets self.s3_url and returns it.
        """
        retstr = self.default_s3_base_url_get() + str(self.default_filename)
        self.s3_url = retstr
        return retstr

    def s3_upload(self):
        """
        Upload the locally-cached snapshot TAR to S3 byte-for-byte under its '.tgz' key.

        Override of DataFileSuper.s3_upload(), which bzip2-compresses UNCOMPRESSED data and streams
        BZIP2 data — neither is correct for an already-gzipped TAR.  Sets s3_stored / s3_url and
        returns the created object so CleanupPolicy still functions.
        """
        self._ensure_s3_url()
        bucket = boto3.resource('s3').Bucket(self.s3_bucket)
        match self.local_storage_type:
            case LocalStorageType.SNAPSHOT_TGZ:
                with open(self.local_filepath_tgz, 'rb') as tgz_fh:
                    s3_object = bucket.put_object(Key=self.s3_path, Body=tgz_fh)
            case _:
                raise ValueError(f'cannot upload a snapshot without a local .tgz file: {self}')
        self.s3_stored = True
        self.s3_url = f's3://{self.s3_bucket}/{self.s3_path}'
        logger.info(f'uploaded {self.s3_url}')
        return s3_object

    def s3_download(self):
        """
        Download the snapshot TAR from S3 into local_filepath_tgz and set local_storage_type to
        SNAPSHOT_TGZ (DataFileSuper.s3_download() hard-codes BZIP2, which is wrong for a TAR).
        """
        self._ensure_s3_url()
        bucket = boto3.resource('s3').Bucket(self.s3_bucket)
        bucket.download_file(Key=self.s3_path, Filename=str(self.local_filepath_tgz))
        self.local_storage_type = LocalStorageType.SNAPSHOT_TGZ

    def write_to_path(self, dest: Path):
        """Copy the locally-cached TAR to dest, downloading from S3 first if UNCACHED."""
        match self.local_storage_type:
            case LocalStorageType.UNCACHED | LocalStorageType.UNSPECIFIED:
                self.s3_download()
                shutil.copy2(self.local_filepath_tgz, dest)
            case LocalStorageType.SNAPSHOT_TGZ:
                shutil.copy2(self.local_filepath_tgz, dest)
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')

    # --- local-cache cleanup --------------------------------------------------------------------

    def _cleanup_local_cache(self):
        """
        Unlink the locally-cached TAR (if any) and mark storage as UNCACHED.  Shared by __del__ and
        __exit__; callers gate on _should_cleanup().
        """
        match self.local_storage_type:
            case LocalStorageType.SNAPSHOT_TGZ:
                os.unlink(self.local_filepath_tgz)
                self.local_storage_type = LocalStorageType.UNCACHED
            case LocalStorageType.UNCACHED | LocalStorageType.UNSPECIFIED:
                pass
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')

    def unlink_cached(self):
        """
        If there is a locally-cached TAR, unlink it.  If there's already NOT a copy, log a warning
        (just once) but don't raise.
        """
        match self.local_storage_type:
            case LocalStorageType.SNAPSHOT_TGZ:
                try:
                    os.unlink(self.local_filepath_tgz)
                    self.local_storage_type = LocalStorageType.UNCACHED
                except FileNotFoundError:
                    if type(self).warned_unlink_cached_none_found < 1:
                        logger.warning(f'file already does not exist (warning only once): {self}')
                    type(self).warned_unlink_cached_none_found += 1
            case LocalStorageType.UNCACHED:
                if type(self).warned_file_already_does_not_exist < 1:
                    logger.warning(f'file already does not exist (warning only once): {self}')
                type(self).warned_file_already_does_not_exist += 1
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')

    # --- JSON-only operations that are invalid on a snapshot TAR --------------------------------

    @property
    def json_data_cache(self):
        raise TypeError(
            'a snapshot TAR is not a JSON document; read it via validate_tar()/extract_summary_file()'
        )

    def write_json(self, data: dict | list):
        raise TypeError('write_json() is not valid on a snapshot TAR (SnapshotFile)')

    def bzip2_compress(self):
        raise TypeError('a snapshot TAR is already gzip-compressed and must not be bz2-compressed')

    def infer_local_storage_type(self, path) -> LocalStorageType:
        raise TypeError(
            'infer_local_storage_type() does JSON/bz2 sniffing, invalid on a snapshot TAR; a '
            'SnapshotFile cache is always LocalStorageType.SNAPSHOT_TGZ'
        )

    def open_for_read(self):
        raise TypeError(
            'open_for_read() returns a JSON/bz2 handle; read a snapshot TAR via validate_tar()/'
            'extract_summary_file() (which use tarfile)'
        )

    # --- TAR-content operations (read the already-acquired local .tgz) ---------------------------

    def _iter_uncompressed_chunks(self, chunk_size: int = 256 * 1024):
        """
        Yield the snapshot TAR content in chunks of bytes, downloading from S3 first when UNCACHED.

        Override of DataFileSuper._iter_uncompressed_chunks(), whose UNCACHED path opens a bz2
        handle.  A snapshot is stored byte-for-byte as its published '.tgz', so those bytes ARE the
        canonical file content: the inherited sha256_digest() / size_bytes_uncompressed() (feeding
        archive_file.our_sha256 / our_size_bytes) hash and measure the .tgz as published — NOT a
        gunzipped TAR stream — keeping them comparable to upstream checksums.
        """
        match self.local_storage_type:
            case LocalStorageType.SNAPSHOT_TGZ:
                pass
            case LocalStorageType.UNCACHED | LocalStorageType.UNSPECIFIED:
                self.s3_download()
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')
        with open(self.local_filepath_tgz, 'rb') as tgz_fh:
            while True:
                chunk = tgz_fh.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def validate_tar(self) -> bool:
        """
        Confirm the locally-cached TAR is complete and readable.

        Opens the '.tgz' and reads every regular member in full; a truncated or corrupt archive
        raises somewhere in tarfile, which we catch.  Contract: returns True when the whole archive
        reads cleanly, and False (logging the cause) when it does not — it does NOT raise on a bad
        TAR, so the crawler can simply skip-and-continue (a later run re-downloads it).  Raises only
        when there is no local '.tgz' to validate.
        """
        if self.local_storage_type != LocalStorageType.SNAPSHOT_TGZ:
            raise ValueError(f'cannot validate a snapshot without a local .tgz file: {self}')
        retval = True
        try:
            with tarfile.open(self.local_filepath_tgz, 'r:*') as tar_reader:
                for member in tar_reader.getmembers():
                    if not member.isfile():
                        continue
                    member_reader = tar_reader.extractfile(member)
                    while member_reader.read(1024 * 64):
                        pass
        except Exception:
            logger.exception(f'TAR_FAILED_VALIDATION {self}')
            retval = False
        return retval

    def extract_summary_file(self, output_dir: Path | None = None) -> SnapshotSummaryFile:
        """
        Extract the rpki-client output JSON member (matching summary_member_re) from the
        locally-cached TAR and return an UNCOMPRESSED SnapshotSummaryFile wrapping it.

        Exactly one member must match summary_member_re (raises KeyError if none, ValueError if more
        than one).  The summary is written under output_dir (default: this snapshot's
        local_storage_dir) and left UNCOMPRESSED; SnapshotSummaryFile.s3_upload() bzip2-compresses on
        upload.  The returned summary is named by THIS snapshot's datetimestamp (not the in-TAR member
        path), tying summary identity to the snapshot it came from.
        """
        if self.local_storage_type != LocalStorageType.SNAPSHOT_TGZ:
            raise ValueError(f'cannot extract a summary without a local .tgz file: {self}')
        if output_dir is None:
            output_dir = self.local_storage_dir
        member_re = re.compile(self.summary_member_re)
        matched_member_name = None
        summary_bytes: bytes | None = None
        with tarfile.open(self.local_filepath_tgz, 'r:*') as tar_reader:
            for member in tar_reader.getmembers():
                if not member.isfile():
                    continue
                if not member_re.match(member.name):
                    continue
                if matched_member_name is not None:
                    raise ValueError(
                        f'expected exactly one member matching {self.summary_member_re!r} in '
                        f'{self.local_filepath_tgz}; found multiple: '
                        f'{matched_member_name} and {member.name}'
                    )
                extracted = tar_reader.extractfile(member)
                if extracted is None:
                    continue
                matched_member_name = member.name
                summary_bytes = extracted.read()
        if summary_bytes is None:
            raise KeyError(
                f'no member matching {self.summary_member_re!r} in {self.local_filepath_tgz}'
            )
        summary = SnapshotSummaryFile(datetimestamp=self.datetimestamp, local_storage_dir=output_dir)
        with open(summary.local_filepath_uncompressed, 'wb') as summary_fh:
            summary_fh.write(summary_bytes)
        summary.local_storage_type = LocalStorageType.UNCOMPRESSED
        return summary

    # --- archive_file SQL row lifecycle (see the module docstring) -------------------------------

    @property
    def source_id(self) -> int | None:
        """
        The archive_file.source_id FK value, read from self.source; None while the source is
        unknown.
        """
        if self.source is not None:
            retval = self.source.id
        else:
            retval = None
        return retval

    @staticmethod
    def _utc_naive(dt: datetime) -> datetime:
        """
        Convert a datetime to naive UTC for the tz-less DATETIME columns (which store UTC by
        convention).  A naive input is assumed to already be UTC.
        """
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        retval = dt.replace(tzinfo=None)
        return retval

    def _ensure_db_identity(self):
        """Raise ValueError unless the (source_id, source_url) archive_file PK is known."""
        if self.source_id is None or self.source_url is None:
            raise ValueError(f'archive_file operations need source and source_url: {self}')

    def db_row_exists(self, db: 'mariadb.SyncConnection') -> bool:
        """
        Return True if the archive_file table already has a row for this snapshot, checked by the
        (source_id, source_url) primary key.
        """
        self._ensure_db_identity()
        cursor = db.cursor()
        try:
            cursor.execute(
                'SELECT 1 FROM archive_file WHERE source_id = ? AND source_url = ?',
                (self.source_id, self.source_url),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
        retval = row is not None
        return retval

    def db_insert_discovered(
            self,
            db: 'mariadb.SyncConnection',
            file_type: DataFileType | None = None,
            discovered_datetime: datetime | None = None,
    ):
        """
        INSERT the archive_file row recording this snapshot's discovery on the archive site.

        Only discovery-time columns are populated: the (source_id, source_url) PK,
        filename_derived_datetime (= self.datetimestamp, the timestamp INFERRED from the
        filename), discovered_datetime (default: now), and file_type_id when file_type is given.
        The our_* columns and observation_datetime stay NULL until db_update_our_copy() /
        db_update_ingested().
        """
        self._ensure_db_identity()
        if discovered_datetime is None:
            discovered_datetime = datetime.now(timezone.utc)
        self.discovered_datetime = discovered_datetime
        if file_type is not None:
            file_type_id = file_type.id
        else:
            file_type_id = None
        cursor = db.cursor()
        try:
            cursor.execute(
                'INSERT INTO archive_file (source_id, source_url, filename_derived_datetime,'
                ' discovered_datetime, file_type_id) VALUES (?, ?, ?, ?, ?)',
                (
                    self.source_id,
                    self.source_url,
                    self._utc_naive(self.datetimestamp),
                    self._utc_naive(discovered_datetime),
                    file_type_id,
                ),
            )
        finally:
            cursor.close()

    def db_insert_ingested(
            self,
            db: 'mariadb.SyncConnection',
            file_type: DataFileType | None,
            discovered_datetime: datetime,
            observation_datetime: datetime,
            our_s3_url: str | None = None,
            our_size_bytes: int | None = None,
            our_stored_datetime: datetime | None = None,
    ):
        """
        INSERT a complete archive_file row for a snapshot whose discovery/ingest history is being
        INFERRED after the fact (reconcile's sql-data-file-to-sql-archive-file subcommand),
        rather than observed live by the crawler.

        Unlike db_insert_discovered(), observation_datetime is already known — the row is born
        ingested — and discovered_datetime is the caller's backdated estimate.  The our_* values,
        when given, come from an S3 bucket listing rather than reading the file; our_sha256 is
        left NULL, since populating it would require downloading every TAR.
        """
        self._ensure_db_identity()
        self.discovered_datetime = discovered_datetime
        self.observation_datetime = observation_datetime
        if file_type is not None:
            file_type_id = file_type.id
        else:
            file_type_id = None
        if our_stored_datetime is not None:
            our_stored_naive = self._utc_naive(our_stored_datetime)
        else:
            our_stored_naive = None
        cursor = db.cursor()
        try:
            cursor.execute(
                'INSERT INTO archive_file (source_id, source_url, filename_derived_datetime,'
                ' discovered_datetime, file_type_id, observation_datetime, our_s3_url,'
                ' our_size_bytes, our_stored_datetime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    self.source_id,
                    self.source_url,
                    self._utc_naive(self.datetimestamp),
                    self._utc_naive(discovered_datetime),
                    file_type_id,
                    self._utc_naive(observation_datetime),
                    our_s3_url,
                    our_size_bytes,
                    our_stored_naive,
                ),
            )
        finally:
            cursor.close()

    def db_update_our_copy(
            self,
            db: 'mariadb.SyncConnection',
            stored_datetime: datetime | None = None,
    ):
        """
        UPDATE this snapshot's archive_file row with the our_* columns describing our stored S3
        copy: our_s3_url, our_size_bytes, our_sha256, and our_stored_datetime (default: now; pass
        the S3 object's LastModified when reconciling from a bucket listing).

        Call after s3_upload() so s3_url is known; size and sha256 stream the cached .tgz,
        re-downloading from S3 when the local cache was already cleaned up.
        """
        self._ensure_db_identity()
        if self.s3_url is None:
            raise ValueError(f'cannot record our stored copy without s3_url: {self}')
        if stored_datetime is None:
            stored_datetime = datetime.now(timezone.utc)
        cursor = db.cursor()
        try:
            cursor.execute(
                'UPDATE archive_file SET our_s3_url = ?, our_size_bytes = ?, our_sha256 = ?,'
                ' our_stored_datetime = ? WHERE source_id = ? AND source_url = ?',
                (
                    self.s3_url,
                    self.size_bytes_uncompressed(),
                    self.sha256_digest(),
                    self._utc_naive(stored_datetime),
                    self.source_id,
                    self.source_url,
                ),
            )
        finally:
            cursor.close()

    def db_update_ingested(self, db: 'mariadb.SyncConnection', observation_datetime: datetime):
        """
        UPDATE this snapshot's archive_file row with observation_datetime, whose non-NULL state
        doubles as the ingested marker (there is deliberately no ingested_datetime column).

        observation_datetime is the authoritative metadata.buildtime read from the extracted
        summary (SnapshotSummaryFile.observation_datetime), NOT this snapshot's filename-derived
        datetimestamp — the caller has the summary in hand at ingest time and passes it in.
        """
        self._ensure_db_identity()
        self.observation_datetime = observation_datetime
        cursor = db.cursor()
        try:
            cursor.execute(
                'UPDATE archive_file SET observation_datetime = ?'
                ' WHERE source_id = ? AND source_url = ?',
                (self._utc_naive(observation_datetime), self.source_id, self.source_url),
            )
        finally:
            cursor.close()

    @classmethod
    def from_db_row(cls, row, db: 'mariadb.SyncConnection' = None) -> 'SnapshotFile':
        """
        Instantiate from an archive_file row (named tuple of the columns selected by
        db_select_within_range): UNCACHED, with explicit s3_url (row.our_s3_url; None when we
        have no stored copy) and source_url, so the process-global default S3 base URL is never
        consulted.  datetimestamp comes from the filename_derived_datetime column, falling back
        to parsing the rpki-<ts>.tgz filename inside source_url when NULL (raising ValueError
        when that does not parse either).  DATETIME columns come back tz-aware UTC, and row
        sha256/size seed the metadata cache so accessors need not re-read the file.
        """
        if row.filename_derived_datetime is not None:
            datetimestamp = row.filename_derived_datetime.replace(tzinfo=timezone.utc)
        else:
            source_url_path = Path(urllib.parse.urlparse(row.source_url).path)
            datetimestamp = cls.infer_datetimestamp_from_path(source_url_path)
        retval = cls(
            datetimestamp=datetimestamp,
            local_storage_type=LocalStorageType.UNCACHED,
            s3_url=row.our_s3_url,
            s3_stored=row.our_s3_url is not None,
            source_url=row.source_url,
        )
        retval.source = DataFileSource.get_by_id(row.source_id, db=db)
        if row.discovered_datetime is not None:
            retval.discovered_datetime = row.discovered_datetime.replace(tzinfo=timezone.utc)
        if row.observation_datetime is not None:
            retval.observation_datetime = row.observation_datetime.replace(tzinfo=timezone.utc)
        if row.our_sha256 is not None:
            retval._metadata_cache['sha256_digest'] = row.our_sha256
        if row.our_size_bytes is not None:
            retval._metadata_cache['size_bytes_uncompressed'] = row.our_size_bytes
        return retval

    @classmethod
    def db_select_within_range(
            cls,
            db: 'mariadb.SyncConnection',
            source: DataFileSource,
            datetime_min: datetime | None = None,
            datetime_max: datetime | None = None,
            ingested: bool | None = None,
    ) -> list['SnapshotFile']:
        """
        Return SnapshotFiles for one source's archive_file rows, sorted by datetimestamp.

        ingested filters on the observation_datetime marker: True = ingested rows only, False =
        the not-yet-ingested backlog, None = both.  The datetime bounds (naive values assumed
        UTC) and the ordering are SQL-side on the indexed filename_derived_datetime column; note
        a bound therefore excludes rows where that column is NULL (from_db_row's fallback of
        parsing source_url only applies to boundless selects).  Rows yielding no timestamp at
        all are skipped with a warning.
        """
        statement = (
            'SELECT source_id, source_url, filename_derived_datetime, discovered_datetime,'
            ' file_type_id, our_s3_url, our_size_bytes, our_sha256, our_stored_datetime,'
            ' observation_datetime FROM archive_file WHERE source_id = ?'
        )
        params = [source.id]
        if datetime_min is not None:
            statement += ' AND filename_derived_datetime >= ?'
            params.append(cls._utc_naive(datetime_min))
        if datetime_max is not None:
            statement += ' AND filename_derived_datetime <= ?'
            params.append(cls._utc_naive(datetime_max))
        match ingested:
            case True:
                statement += ' AND observation_datetime IS NOT NULL'
            case False:
                statement += ' AND observation_datetime IS NULL'
            case None:
                pass
        statement += ' ORDER BY filename_derived_datetime'
        cursor = db.cursor(named_tuple=True)
        try:
            cursor.execute(statement, tuple(params))
            rows = cursor.fetchall()
        finally:
            cursor.close()
        retlist = []
        for row in rows:
            try:
                snapshot = cls.from_db_row(row, db=db)
            except ValueError:
                logger.warning(f'skipping archive_file row with unparseable source_url: {row.source_url}')
                continue
            retlist.append(snapshot)
        # SQL already orders by filename_derived_datetime; re-sort only to place any
        # NULL-column rows (datetimestamp via the source_url fallback) correctly.
        retlist.sort(key=lambda snapshot: snapshot.datetimestamp)
        return retlist
