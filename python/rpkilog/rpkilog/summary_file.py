import bz2
import json
from datetime import datetime
from pathlib import Path

from rpkilog.data_file_super import DataFileSuper
from rpkilog.local_storage_type import LocalStorageType


def make_filename(datetimestamp: datetime, local_storage_dir: Path) -> Path:
    retpath = Path(local_storage_dir, datetimestamp.strftime('%Y-%m-%dT%H%M%SZ.summary.json'))
    return retpath


class SummaryFile(DataFileSuper):
    default_filename_strftime_expression = '%Y-%m-%dT%H%M%SZ.summary.json'

    def __init__(
            self,
            datetimestamp: datetime,
            cleanup_upon_destroy: bool = False,
            local_filepath_uncompressed: Path = None,
            local_filepath_bz2: Path = None,
            local_storage_dir: Path = None,
            local_storage_type: LocalStorageType = LocalStorageType.UNSPECIFIED,
            s3_url: str = None,
            s3_stored: bool = False
    ):
        super().__init__(
            datetimestamp=datetimestamp,
            cleanup_upon_destroy=cleanup_upon_destroy,
            local_filepath_uncompressed=local_filepath_uncompressed,
            local_filepath_bz2=local_filepath_bz2,
            local_storage_dir=local_storage_dir,
            local_storage_type=local_storage_type,
            s3_url=s3_url,
            s3_stored=s3_stored,
        )

    @classmethod
    def new_from_dict(
            cls,
            datetimestamp: datetime,
            local_storage_dir: Path,
            summary_dict: dict = None,
    ):
        retobj = cls(
            datetimestamp=datetimestamp,
            local_storage_type=LocalStorageType.BZIP2,
        )
        summary_fh = bz2.open(filename=retobj.local_filepath_bz2, mode='xt')
        json.dump(summary_dict, summary_fh)
        summary_fh.close()
        return retobj
