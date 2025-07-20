import os
from abc import ABC
import bz2
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import TextIO, Union
import urllib.parse

import boto3
import dateutil.parser

from rpkilog.local_storage_type import LocalStorageType

logger = logging.getLogger(__name__)


class DataFileSuper(ABC):
    """
    Superclass for RoutinatorSnapshotFile, SummaryFile, and others.  This helps with bzipping, S3 uploads,
    and other things common to the different types of files we work with.
    """
    default_filename_strftime_expression: str
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
            local_storage_dir: Path = None,
            local_storage_type: LocalStorageType = LocalStorageType.UNSPECIFIED,
            s3_url: str = None,
            s3_stored: bool = False,
    ):
        self.datetimestamp = datetimestamp
        self.cleanup_upon_destroy = cleanup_upon_destroy
        self.local_filepath_bz2 = local_filepath_bz2
        self.local_filepath_uncompressed = local_filepath_uncompressed
        self.local_storage_type = local_storage_type
        self.local_storage_dir = local_storage_dir
        self.s3_stored = s3_stored
        self.s3_url = s3_url
        self._json_data_cache = None

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
                    os.unlink(self.local_filepath_uncompressed)
                    self.local_storage_type = LocalStorageType.UNCACHED
                case LocalStorageType.BZIP2:
                    os.unlink(self.local_filepath_bz2)
                    self.local_storage_type = LocalStorageType.UNCACHED

    def __repr__(self):
        # TODO: move this to a classvar so it can be overridden
        include_attrs = [
            'datetimestamp',
            'local_filepath_uncompressed',
            'local_filepath_bz2',
            'local_storage_type',
            's3_url',
            's3_stored',
        ]
        brief_dict = {}
        for aname in include_attrs:
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
        bz2_fh.close()
        self.local_storage_type = LocalStorageType.BZIP2
        os.unlink(self.local_filepath_uncompressed)

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
        """
        try:
            fh = bz2.open(filename=path, mode='r')
            _ = json.load(fh)
            fh.close()
            self.local_storage_type = LocalStorageType.BZIP2
            self.local_filepath_bz2 = path
            return self.local_storage_type
        except OSError:
            # bz2 raises OSError when you open a non-bz2 file and try to read from it.
            pass

        fh = open(file=path, mode='rt')
        _ = json.load(fh)
        fh.close()
        self.local_storage_type = LocalStorageType.UNCOMPRESSED
        self.local_filepath_uncompressed = path
        return self.local_storage_type

    @property
    def json_data_cache(self):
        if not self._json_data_cache:
            fh = self.open_for_read()
            self._json_data_cache = json.load(fh)
        return self._json_data_cache

    @property
    def local_filepath_bz2(self) -> Path:
        if self._local_filepath_bz2:
            return self._local_filepath_bz2
        retpath = Path(self.local_storage_dir, self.default_filename())
        return retpath

    @local_filepath_bz2.setter
    def local_filepath_bz2(self, value: Path):
        self._local_filepath_bz2 = value

    @property
    def local_filepath_uncompressed(self) -> Path:
        if self._local_filepath_uncompressed:
            return self._local_filepath_uncompressed
        retpath = Path(self.local_storage_dir, self.default_filename())
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
        url = urllib.parse.urlparse(self.s3_url)
        return url.netloc

    def s3_download(self):
        bucket = boto3.resource('s3').Bucket(self.s3_bucket())
        bucket.download_file(
            key=self.s3_path,
            filename=self.local_filepath_bz2,
        )
        self.local_storage_type = LocalStorageType.BZIP2

    def s3_path(self) -> str:
        url = urllib.parse.urlparse(self.s3_url)
        retstr = url.path.lstrip('/')
        return retstr

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
        self.s3_url = f's3://{self.s3_bucket()}/{self.s3_path()}'
        logger.info(f'uploaded {self.s3_url}')
        self.cleanup_upon_destroy = True
        return s3_object

    @property
    def s3_url(self) -> str:
        if self._s3_url:
            return self._s3_url
        retstr = self.default_s3_base_url_get() + str(self.default_filename()) + '.bz2'
        return retstr

    @s3_url.setter
    def s3_url(self, value: str):
        # allow exception to be raised if urlparse fails even though we don't need the value immediately
        _ = urllib.parse.urlparse(value)
        self._s3_url = value

    def unlink_cached(self):
        """
        If there is a locally-cached copy of the snapshot, unlink it.
        If there's already NOT a copy, log a warning (just once) but don't raise an exception.

        I think self.cleanup_upon_destroy will make this method unnecessary.  Maybe remove it.
        """
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                try:
                    os.unlink(self.local_filepath_uncompressed)
                    self.local_storage_type = LocalStorageType.UNCACHED
                except FileNotFoundError:
                    if self.warned_unlink_cached_none_found < 1:
                        logger.warning(f'file already does not exist (warning only once): {self}')
                    self.warned_unlink_cached_none_found += 1
            case LocalStorageType.BZIP2:
                try:
                    os.unlink(self.local_filepath_bz2)
                    self.local_storage_type = LocalStorageType.UNCACHED
                except FileNotFoundError:
                    if self.warned_unlink_cached_none_found < 1:
                        logger.warning(f'file already does not exist (warning only once): {self}')
            case LocalStorageType.UNCACHED:
                logger.warning(f'file already does not exist (warning only once): {self}')
            case _:
                logger.warning(f'unexpected value of LocalStorageType: {self}')
