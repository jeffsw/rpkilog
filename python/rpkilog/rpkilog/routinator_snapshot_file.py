import bz2
from datetime import datetime, timezone
from enum import Enum
import logging
import urllib.parse
import urllib.request
from os import unlink
from pathlib import Path
from typing import TextIO

import boto3

logger = logging.getLogger()


class LocalStorageType(Enum):
    UNSPECIFIED = 0
    UNCACHED = 1
    UNCOMPRESSED = 2
    BZIP2 = 3


class RoutinatorSnapshotFile:
    # used by property getter/setter
    _default_s3_base_url: str = None
    default_local_storage_dir: Path = None
    # warning deduplication so log won't get spammy about minor issues
    warned_compress_invoked_on_already_compressed_snapshot = 0
    warned_default_local_storage_dir_unconfigured = 0
    warned_unlink_cached_none_found = 0

    def __init__(
            self,
            datetimestamp: datetime,
            cleanup_upon_destroy: bool = False,
            local_filepath_uncompressed: Path = None,
            local_filepath_bz2: Path = None,
            local_storage_type: LocalStorageType = LocalStorageType.UNSPECIFIED,
            s3_storage_url: str = None,
            s3_stored: bool = False,
    ):
        self.datetimestamp = datetimestamp
        self.cleanup_upon_destroy = cleanup_upon_destroy
        self.local_storage_type = local_storage_type
        self.s3_stored = s3_stored

        if local_filepath_uncompressed:
            self.local_filepath_uncompressed = local_filepath_uncompressed
        elif self.default_local_storage_dir:
            self.local_filepath_uncompressed = Path(self.default_local_storage_dir, self.default_filename())
        else:
            if self.warned_default_local_storage_dir_unconfigured == 0:
                logger.warning(f'default_local_storage_dir is unconfigured AND object created with none: {self}')
            self.warned_default_local_storage_dir_unconfigured += 1

        if local_filepath_bz2:
            self.local_filepath_bz2 = local_filepath_bz2
        elif self.default_local_storage_dir:
            self.local_filepath_bz2 = Path(self.default_local_storage_dir, self.default_filename() + '.bz2')
        else:
            if self.warned_default_local_storage_dir_unconfigured == 0:
                logger.warning(f'default_local_storage_dir is unconfigured AND object created with none: {self}')
            self.warned_default_local_storage_dir_unconfigured += 1

        if s3_storage_url:
            self.s3_storage_url = s3_storage_url
        else:
            self.s3_storage_url = str(self.default_s3_base_url_get()) + self.default_filename() + '.bz2'

    def __del__(self):
        """
        Clean up cached files on disk when destructor invoked AND self.cleanup_upon_destroy == True.

        Generally, self.cleanup_upon_destroy will be set true if a snapshot is uploaded to S3.  A caller
        could override that by setting it back to false after an upload.

        Caller can also manually set it to True.  Maybe they want this after summarization.
        """
        if self.cleanup_upon_destroy:
            match self.local_storage_type:
                case LocalStorageType.UNCOMPRESSED:
                    unlink(self.local_filepath_uncompressed)
                    self.local_storage_type = LocalStorageType.UNCACHED
                case LocalStorageType.BZIP2:
                    unlink(self.local_filepath_bz2)
                    self.local_storage_type = LocalStorageType.UNCACHED

    @classmethod
    def fetch_from_routinator(cls, base_url: str = 'http://localhost:8323/'):
        url = base_url.rstrip('/') + '/jsonext'
        now = datetime.now(tz=timezone.utc)
        new_filename = Path(cls.default_local_storage_dir, now.strftime('%Y-%m-%dT%H%M%SZ.routinator.jsonext'))
        (retrieved_filename, retrieved_headers) = urllib.request.urlretrieve(
            url=url,
            filename=new_filename,
        )
        logger.info(f'fetched jsonext from routinator to filename {retrieved_filename}')
        retval = cls(
            datetimestamp=now,
            local_filepath_uncompressed=Path(retrieved_filename),
            local_storage_type=LocalStorageType.UNCOMPRESSED,
        )
        return retval

    def bzip2_compress(self):
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                pass
            case LocalStorageType.UNCACHED:
                raise ValueError(f'cannot compress when there is no locally-cached snapshot file: {self}')
            case LocalStorageType.BZIP2:
                if self.warned_compress_invoked_on_already_compressed_snapshot < 1:
                    logger.warning(f'compress invoked on already-compressed snapshot file: {self}')
                self.warned_compress_invoked_on_already_compressed_snapshot += 1
                return
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')

        uncomp_fh = open(self.local_filepath_uncompressed, mode='rb')
        bz2_fh = bz2.open(self.local_filepath_bz2, mode='xb')
        bz2_fh.write(uncomp_fh.read())
        self.local_storage_type = LocalStorageType.BZIP2
        unlink(self.local_filepath_uncompressed)

    def default_filename(self) -> str:
        retstr = self.datetimestamp.strftime('%Y-%m-%dT%H%M%SZ.routinator.jsonext')
        return retstr

    @classmethod
    def default_s3_base_url_get(cls) -> str:
        return cls._default_s3_base_url

    @classmethod
    def default_s3_base_url_set(cls, value):
        """
        This setter exists purely to ensure the URL contains at least one '/' after the hostname/netloc.
        For example, if you give it 'http://bucket' it will set the value to 'http://bucket/'.
        """
        u1 = urllib.parse.urlparse(value)
        if u1.path == '':
            cls._default_s3_base_url = str(u1) + '/'
        else:
            cls._default_s3_base_url = str(u1)

    def open_for_read(self) -> TextIO:
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                retfh = open(self.local_filepath_uncompressed)
            case LocalStorageType.BZIP2:
                retfh = bz2.open(self.local_filepath_bz2, mode='rb')
            case LocalStorageType.UNCACHED:
                self.s3_download()
                retfh = bz2.open(self.local_filepath_bz2, mode='rb')
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')
        return retfh

    def s3_bucket(self) -> str:
        url = urllib.parse.urlparse(self.s3_storage_url)
        return url.netloc

    def s3_download(self):
        bucket = boto3.resource('s3').Bucket(self.s3_bucket())
        bucket.download_file(
            key=self.s3_path,
            filename=self.local_filepath_bz2,
        )
        self.local_storage_type = LocalStorageType.BZIP2

    def s3_path(self) -> str:
        url = urllib.parse.urlparse(self.s3_storage_url)
        return url.path

    def s3_upload(self):
        bucket = boto3.resource('s3').Bucket(self.s3_bucket())
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                uncomp_fh = open(self.local_filepath_uncompressed, 'rb')
                data_uncompressed = uncomp_fh.read()
                uncomp_fh.close()
                data_bz2 = bz2.compress(data_uncompressed)
                s3_object = bucket.put_object(Key=self.s3_path(), Body=data_bz2)
            case LocalStorageType.BZIP2:
                bz2_fh = open(self.local_filepath_bz2, 'rb')
                s3_object = bucket.put_object(Key=self.s3_path(), Body=bz2_fh)
            case _:
                raise ValueError(f'cannot upload without a local file to upload from: {self}')
        self.s3_storage_url = f's3://{self.s3_bucket()}/{self.s3_path()}'
        self.cleanup_upon_destroy = True
        return s3_object

    def unlink_cached(self):
        """
        If there is a locally-cached copy of the snapshot, unlink it.
        If there's already NOT a copy, log a warning (just once) but don't raise an exception.

        I think self.cleanup_upon_destroy will make this method unnecessary.  Maybe remove it.
        """
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                try:
                    unlink(self.local_filepath_uncompressed)
                    self.local_storage_type = LocalStorageType.UNCACHED
                except FileNotFoundError:
                    if self.warned_unlink_cached_none_found < 1:
                        logger.warning(f'file already does not exist (warning only once): {self}')
                    self.warned_unlink_cached_none_found += 1
            case LocalStorageType.BZIP2:
                try:
                    unlink(self.local_filepath_bz2)
                    self.local_storage_type = LocalStorageType.UNCACHED
                except FileNotFoundError:
                    if self.warned_unlink_cached_none_found < 1:
                        logger.warning(f'file already does not exist (warning only once): {self}')
            case LocalStorageType.UNCACHED:
                logger.warning(f'file already does not exist (warning only once): {self}')
            case _:
                logger.warning(f'unexpected value of LocalStorageType: {self}')
