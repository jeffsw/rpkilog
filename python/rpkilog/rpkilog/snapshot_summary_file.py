import bz2
from datetime import datetime, timezone
import re

import dateutil.parser

from rpkilog.data_file_super import DataFileSuper
from rpkilog.local_storage_type import LocalStorageType


class SnapshotSummaryFile(DataFileSuper):
    """
    Represents an rpkiclient snapshot-summary file: YYYYMMDDTHHMMSSZ.json[.bz2]

    These are produced by rpkilog-rpkiclient-uploader and stored in the snapshot-summary S3 bucket.
    """
    default_filename_strftime_expression = '%Y%m%dT%H%M%SZ.json'
    # minimum uncompressed byte size of a valid rpkiclient output JSON
    MINIMUM_SIZE = 8_500_000

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
        Extract the buildtime datetime from rpkiclient metadata.

        dateutil.parser.parse() returns a naive datetime if the buildtime string has no timezone
        indicator.  Like the base class, we call .replace(tzinfo=timezone.utc) after parsing for
        consistency and robustness against malformed input.
        """
        dt = dateutil.parser.parse(json_data['metadata']['buildtime'])
        retval = dt.replace(tzinfo=timezone.utc)
        return retval

    def validate_size(self):
        """
        Raise RuntimeError if the uncompressed data is below MINIMUM_SIZE bytes.

        The BZIP2 branch streams the decompressed bytes in 256 KiB chunks and counts them rather
        than reading the whole file into memory, avoiding a memory spike on large files.
        """
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                size = self.local_filepath_uncompressed.stat().st_size
            case LocalStorageType.BZIP2:
                size = 0
                with bz2.open(self.local_filepath_bz2, 'rb') as fh:
                    while True:
                        chunk = fh.read(256 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
            case _:
                raise ValueError(f'cannot validate size without a locally-cached file: {self}')
        if size < self.MINIMUM_SIZE:
            raise RuntimeError(f'file too small ({size} bytes < {self.MINIMUM_SIZE}): {self}')
