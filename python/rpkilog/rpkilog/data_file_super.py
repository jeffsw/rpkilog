import os
import shutil
from abc import ABC
import bz2
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Union, IO
import urllib.parse

import boto3
import dateutil.parser
from botocore.exceptions import ClientError

from rpkilog.cleanup_policy import CleanupPolicy
from rpkilog.local_storage_type import LocalStorageType

logger = logging.getLogger(__name__)


class DataFileSuper(ABC):
    """
    Superclass for RoutinatorSnapshotFile, SummaryFile, and others.  This helps with bzipping, S3 uploads,
    and other things common to the different types of files we work with.
    """
    default_filename_strftime_expression: str
    repr_attrs: list[str] = [
        'datetimestamp',
        'local_filepath_uncompressed',
        'local_filepath_bz2',
        'local_storage_type',
        's3_url',
        's3_stored',
    ]
    # used by property getter/setter
    _default_s3_base_url: str = None
    default_local_storage_dir: Path = None
    # warning deduplication so log won't get spammy about minor issues
    warned_compress_invoked_on_already_compressed_snapshot = 0
    warned_file_already_does_not_exist = 0
    warned_unlink_cached_none_found = 0

    def __init_subclass__(cls, **kwargs):
        """
        Enforce at class-definition time that every concrete subclass defines
        default_filename_strftime_expression.  Without this check, a subclass that omits it would
        instead raise a confusing AttributeError deep inside the default_filename property.
        """
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, 'default_filename_strftime_expression'):
            raise TypeError(
                f"{cls.__name__} must define default_filename_strftime_expression, "
                f"e.g. '%Y%m%dT%H%M%SZ.filetype.json'"
            )

    def __init__(
            self,
            datetimestamp: datetime,
            cleanup_policy: CleanupPolicy = CleanupPolicy.CLEANUP_IF_IN_S3,
            local_filepath_uncompressed: Path = None,
            local_filepath_bz2: Path = None,
            local_storage_dir: Path = None,
            local_storage_type: LocalStorageType = LocalStorageType.UNSPECIFIED,
            s3_url: str = None,
            s3_stored: bool = False,
    ):
        self.datetimestamp = datetimestamp
        self.cleanup_policy = cleanup_policy
        self.local_filepath_bz2 = local_filepath_bz2
        self.local_filepath_uncompressed = local_filepath_uncompressed
        self.local_storage_type = local_storage_type
        self.local_storage_dir = local_storage_dir
        self.s3_stored = s3_stored
        self.s3_url = s3_url
        self._json_data_cache = None

    def __del__(self):
        """
        Clean up cached files on disk when the destructor runs AND self.cleanup_policy permits it
        (see _should_cleanup()).

        Under the default CLEANUP_IF_IN_S3 policy, cleanup happens once the file has been uploaded
        to S3.  A caller can force or suppress cleanup by setting self.cleanup_policy to
        CLEANUP_ALWAYS or CLEANUP_NEVER.

        This destructor is retained as a fallback for instances not used in a `with` block.  When
        deterministic cleanup is desired, prefer the context manager (__enter__/__exit__) instead.
        """
        if self._should_cleanup():
            self._cleanup_local_cache()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Clean up the local cached file on context exit when self.cleanup_policy permits it (see
        _should_cleanup()).  Under the default CLEANUP_IF_IN_S3 policy, s3_upload() sets s3_stored
        True so cleanup happens after a successful upload.  Returns False so any in-flight exception
        is never suppressed.  __del__ remains a fallback for non-`with` usage.
        """
        if self._should_cleanup():
            self._cleanup_local_cache()
        return False

    def _should_cleanup(self) -> bool:
        """
        Decide whether the locally-cached file should be unlinked on destroy/exit, per
        self.cleanup_policy.  CLEANUP_ALWAYS always cleans up, CLEANUP_NEVER never does, and
        CLEANUP_IF_IN_S3 cleans up only once the file is stored in S3.
        """
        match self.cleanup_policy:
            case CleanupPolicy.CLEANUP_ALWAYS:
                retval = True
            case CleanupPolicy.CLEANUP_NEVER:
                retval = False
            case CleanupPolicy.CLEANUP_IF_IN_S3:
                retval = self.s3_stored
            case _:
                raise ValueError(f'unexpected value of cleanup_policy: {self}')
        return retval

    def _cleanup_local_cache(self):
        """
        Unlink the locally-cached file (if any) and mark storage as UNCACHED.  Shared by __del__
        and __exit__; callers gate on _should_cleanup().
        """
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                os.unlink(self.local_filepath_uncompressed)
                self.local_storage_type = LocalStorageType.UNCACHED
            case LocalStorageType.BZIP2:
                os.unlink(self.local_filepath_bz2)
                self.local_storage_type = LocalStorageType.UNCACHED
            case LocalStorageType.UNCACHED | LocalStorageType.UNSPECIFIED:
                pass

    def __repr__(self):
        """
        repr_attrs is a classvar listing the instance attribute names to include.  Subclasses can
        override it to add, remove, or reorder fields — no need to override __repr__ itself:

            class VrpDiffFile(DataFileSuper):
                repr_attrs = DataFileSuper.repr_attrs + ['diff_count']
        """
        brief_dict = {}
        for aname in self.repr_attrs:
            if avalue := getattr(self, aname, None):
                brief_dict[aname] = avalue
        cname = self.__class__.__name__
        retstr = f'{cname}({brief_dict})'
        return retstr
    __str__ = __repr__

    def bzip2_compress(self):
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                pass
            case LocalStorageType.UNCACHED | LocalStorageType.UNSPECIFIED:
                raise ValueError(f'cannot compress when there is no locally-cached snapshot file: {self}')
            case LocalStorageType.BZIP2:
                if type(self).warned_compress_invoked_on_already_compressed_snapshot < 1:
                    logger.warning(f'compress invoked on already-compressed snapshot file: {self}')
                type(self).warned_compress_invoked_on_already_compressed_snapshot += 1
                return
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')

        with open(self.local_filepath_uncompressed, mode='rb') as uncomp_fh:
            with bz2.open(self.local_filepath_bz2, mode='xb') as bz2_fh:
                shutil.copyfileobj(uncomp_fh, bz2_fh, length=1024*1024)
        self.local_storage_type = LocalStorageType.BZIP2
        os.unlink(self.local_filepath_uncompressed)

    @property
    def default_filename(self) -> str:
        retstr = self.datetimestamp.strftime(self.default_filename_strftime_expression)
        return retstr

    @classmethod
    def default_s3_base_url_get(cls) -> str:
        if not cls._default_s3_base_url:
            raise ValueError(f'default_s3_base_url_set() class method MUST be invoked unless providing '
                             f'explicit s3 URLs for each file uploaded')
        return cls._default_s3_base_url

    @classmethod
    def default_s3_base_url_set(cls, value: Union[str, urllib.parse.ParseResult]):
        """
        This setter exists purely to ensure the URL contains at least one '/' after the hostname/netloc.
        For example, if you give it 'http://bucket' it will set the value to 'http://bucket/'.
        """
        if isinstance(value, urllib.parse.ParseResult):
            # instead of deepcopy
            u1 = value
        else:
            u1 = urllib.parse.urlparse(str(value))
        s1 = urllib.parse.urlunparse(u1)
        if u1.path == '':
            cls._default_s3_base_url = s1 + '/'
        else:
            cls._default_s3_base_url = s1

    @classmethod
    def infer_datetimestamp_from_path(cls, path) -> datetime:
        """
        Parse a datetime stamp from the given path and return it.

        May return a ParserError from dateutil.parser, or ValueError if our regex does not match, upon error.
        """
        rem = re.search(r'(?P<dt>\d{4}\D?\d{2}\D?\d{2}T?\d{2}\D?\d{2}\D\d{2}Z?)', path.name)
        if not rem:
            raise ValueError(f'regex did not match a recognized datetimestamp in given path: {path}')
        dt = dateutil.parser.parse(rem.group('dt'))
        retval = dt.replace(tzinfo=timezone.utc)
        return retval

    def infer_local_storage_type(self, path) -> LocalStorageType:
        """
        Examine the given file, trying to open as a bzip2 and then as a json.
        Raise an exception if neither are successful (type of exception depends on how json.load() fails)

        Update self.local_storage_type and self.local_filepath_uncompressed or self.local_filepath_bz2.

        NOTE: Both branches parse the entire JSON just to confirm the file is readable.  Checking only
        the first few bytes for the bz2 magic (\x42\x5a\x68) would be far cheaper for large files.  I've
        kept the full JSON load as a verification step.
        """
        try:
            with bz2.open(filename=path, mode='r') as fh:
                _ = json.load(fh)
            self.local_storage_type = LocalStorageType.BZIP2
            self.local_filepath_bz2 = path
            return self.local_storage_type
        except OSError:
            # bz2 raises OSError when you open a non-bz2 file and try to read from it.
            pass

        with open(file=path, mode='rt') as fh:
            _ = json.load(fh)
        self.local_storage_type = LocalStorageType.UNCOMPRESSED
        self.local_filepath_uncompressed = path
        return self.local_storage_type

    @property
    def json_data_cache(self):
        if not self._json_data_cache:
            with self.open_for_read() as fh:
                self._json_data_cache = json.load(fh)
        return self._json_data_cache

    @property
    def local_filepath_bz2(self) -> Path:
        if self._local_filepath_bz2:
            return self._local_filepath_bz2
        retpath = Path(self.local_storage_dir, self.default_filename + '.bz2')
        return retpath

    @local_filepath_bz2.setter
    def local_filepath_bz2(self, value: Path):
        self._local_filepath_bz2 = value

    @property
    def local_filepath_uncompressed(self) -> Path:
        if self._local_filepath_uncompressed:
            return self._local_filepath_uncompressed
        retpath = Path(self.local_storage_dir, self.default_filename)
        return retpath

    @local_filepath_uncompressed.setter
    def local_filepath_uncompressed(self, value: Path):
        self._local_filepath_uncompressed = value

    @property
    def local_storage_dir(self) -> Path:
        if self._local_storage_dir:
            return self._local_storage_dir
        if self.default_local_storage_dir:
            return self.default_local_storage_dir
        raise ValueError(f'local_storage_dir or default_local_storage_dir MUST be set: {self}')

    @local_storage_dir.setter
    def local_storage_dir(self, value: Path):
        self._local_storage_dir = value

    def open_for_read(self) -> IO[bytes] | IO[str]:
        """
        Kept as a method rather than a property because it returns an open file handle that the
        caller must close — resource factories conventionally stay as methods.
        """
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                retfh = open(self.local_filepath_uncompressed)
            case LocalStorageType.BZIP2:
                retfh = bz2.open(self.local_filepath_bz2, mode='rb')
            case LocalStorageType.UNCACHED | LocalStorageType.UNSPECIFIED:
                self.s3_download()
                retfh = bz2.open(self.local_filepath_bz2, mode='rb')
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')
        return retfh

    @property
    def s3_bucket(self) -> str:
        if self.s3_url is None:
            raise ValueError('s3_url must be set before accessing s3_bucket')
        url = urllib.parse.urlparse(self.s3_url)
        return url.netloc

    def s3_download(self):
        bucket = boto3.resource('s3').Bucket(self.s3_bucket)
        bucket.download_file(
            Key=self.s3_path,
            Filename=str(self.local_filepath_bz2),
        )
        self.local_storage_type = LocalStorageType.BZIP2

    def s3_exists(self) -> bool:
        """
        Return True if the S3 object at self.s3_url already exists.

        Kept as a method rather than a property because it makes a live network call — a property
        that silently hits S3 on every attribute access would be surprising.
        """
        try:
            boto3.client('s3').head_object(Bucket=self.s3_bucket, Key=self.s3_path)
            retval = True
        except ClientError as exc:
            if exc.response['Error']['Code'] == '404':
                retval = False
            else:
                raise
        return retval

    @property
    def s3_path(self) -> str:
        if self.s3_url is None:
            raise ValueError('s3_url must be set before accessing s3_path')
        url = urllib.parse.urlparse(self.s3_url)
        retstr = url.path.lstrip('/')
        return retstr

    def s3_upload(self):
        bucket = boto3.resource('s3').Bucket(self.s3_bucket)
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                uncomp_fh = open(self.local_filepath_uncompressed, 'rb')
                data_uncompressed = uncomp_fh.read()
                uncomp_fh.close()
                data_bz2 = bz2.compress(data_uncompressed)
                s3_object = bucket.put_object(Key=self.s3_path, Body=data_bz2)
            case LocalStorageType.BZIP2:
                with open(self.local_filepath_bz2, 'rb') as bz2_fh:
                    s3_object = bucket.put_object(Key=self.s3_path, Body=bz2_fh)
            case LocalStorageType.UNCACHED | LocalStorageType.UNSPECIFIED:
                raise ValueError(f'cannot upload without a local file to upload from: {self}')
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')
        self.s3_stored = True
        self.s3_url = f's3://{self.s3_bucket}/{self.s3_path}'
        logger.info(f'uploaded {self.s3_url}')
        # s3_stored is now True; under the default CLEANUP_IF_IN_S3 policy the local cache will be
        # unlinked on destroy/exit, while CLEANUP_NEVER leaves an externally owned source file alone.
        return s3_object

    @property
    def s3_url(self) -> str | None:
        return self._s3_url

    @s3_url.setter
    def s3_url(self, value: str | None):
        if value is not None:
            # validate & allow exception to be raised if urlparse fails
            _ = urllib.parse.urlparse(value)
        self._s3_url = value

    def s3_url_set_to_default(self):
        """
        Set self.s3_url to the default value derived from default_s3_base_url and default_filename,
        then return it.

        Kept as a method rather than a property because it has the side effect of mutating self.s3_url.
        """
        retstr = self.default_s3_base_url_get() + str(self.default_filename) + '.bz2'
        self.s3_url = retstr
        return retstr

    def write_json(self, data: dict | list):
        """Write data as JSON to self.local_filepath_uncompressed and update local_storage_type."""
        with open(self.local_filepath_uncompressed, 'wt') as fh:
            json.dump(data, fh)
        self.local_storage_type = LocalStorageType.UNCOMPRESSED

    def write_to_path(self, dest: Path):
        """Copy the locally-cached file to dest, downloading from S3 first if UNCACHED."""
        match self.local_storage_type:
            case LocalStorageType.UNCACHED | LocalStorageType.UNSPECIFIED:
                self.s3_download()
                shutil.copy2(self.local_filepath_bz2, dest)
            case LocalStorageType.BZIP2:
                shutil.copy2(self.local_filepath_bz2, dest)
            case LocalStorageType.UNCOMPRESSED:
                shutil.copy2(self.local_filepath_uncompressed, dest)
            case _:
                raise ValueError(f'unexpected value of local_storage_type: {self}')

    def unlink_cached(self):
        """
        If there is a locally-cached copy of the snapshot, unlink it.
        If there's already NOT a copy, log a warning (just once) but don't raise an exception.
        """
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                try:
                    os.unlink(self.local_filepath_uncompressed)
                    self.local_storage_type = LocalStorageType.UNCACHED
                except FileNotFoundError:
                    if type(self).warned_unlink_cached_none_found < 1:
                        logger.warning(f'file already does not exist (warning only once): {self}')
                    type(self).warned_unlink_cached_none_found += 1
            case LocalStorageType.BZIP2:
                try:
                    os.unlink(self.local_filepath_bz2)
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
                logger.warning(f'unexpected value of LocalStorageType: {self}')
