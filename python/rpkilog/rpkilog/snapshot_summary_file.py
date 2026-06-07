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
        rem = re.search(r'(?P<dt>\d{8}T\d{6}Z)\.json(\.bz2)?$', str(path.name))
        if not rem:
            raise ValueError(f'regex did not match a snapshot-summary filename in given path: {path}')
        dt = dateutil.parser.parse(rem.group('dt'))
        retval = dt.replace(tzinfo=timezone.utc)
        return retval

    @classmethod
    def datetimestamp_from_json(cls, json_data: dict) -> datetime:
        """
        Extract the buildtime datetime from rpkiclient metadata.

        TODO: dateutil.parser.parse() returns a naive datetime if the buildtime string has no
         timezone indicator.  The base class always calls .replace(tzinfo=timezone.utc) after
         parsing; add the same here for consistency and robustness against malformed input.
        """
        retval = dateutil.parser.parse(json_data['metadata']['buildtime'])
        return retval

    def validate_size(self):
        """
        Raise RuntimeError if the uncompressed data is below MINIMUM_SIZE bytes.

        TODO: The BZIP2 branch decompresses the entire file into memory just to count bytes.
         For large files a streaming count avoids the memory spike:
           size = sum(len(chunk) for chunk in iter(lambda: fh.read(65536), b''))
        """
        match self.local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                size = self.local_filepath_uncompressed.stat().st_size
            case LocalStorageType.BZIP2:
                with bz2.open(self.local_filepath_bz2, 'rb') as fh:
                    size = len(fh.read())
            case _:
                raise ValueError(f'cannot validate size without a locally-cached file: {self}')
        if size < self.MINIMUM_SIZE:
            raise RuntimeError(f'file too small ({size} bytes < {self.MINIMUM_SIZE}): {self}')
