from datetime import datetime, timezone
import re

import dateutil.parser

from rpkilog.data_file_super import DataFileSuper


class VrpDiffFile(DataFileSuper):
    """
    Represents a VRP diff file: YYYYMMDDTHHMMSSZ.vrpdiff.json[.bz2]

    These are produced by rpkilog-diff and stored in the vrpdiff S3 bucket.
    """
    default_filename_strftime_expression = '%Y%m%dT%H%M%SZ.vrpdiff.json'

    @classmethod
    def infer_datetimestamp_from_path(cls, path) -> datetime:
        """Extract datetime from a vrpdiff filename; rejects summary filenames."""
        rem = re.search(r'(?P<dt>\d{8}T\d{4,6}Z)\.vrpdiff\.json(\.bz2)?$', str(path.name))
        if not rem:
            raise ValueError(f'regex did not match a vrpdiff filename in given path: {path}')
        dt = dateutil.parser.parse(rem.group('dt'))
        retval = dt.replace(tzinfo=timezone.utc)
        return retval

    @classmethod
    def from_summary_filename(cls, summary_filename: str, **kwargs) -> 'VrpDiffFile':
        """Construct a VrpDiffFile with datetimestamp derived from a snapshot-summary filename."""
        rem = re.search(r'(?P<dt>\d{8}T\d{4,6}Z)\.json(\.bz2)?$', str(summary_filename))
        if not rem:
            raise ValueError(
                f'input does not match snapshot-summary filename pattern: {summary_filename!r}'
            )
        dt = dateutil.parser.parse(rem.group('dt'))
        retval = cls(datetimestamp=dt.replace(tzinfo=timezone.utc), **kwargs)
        return retval
