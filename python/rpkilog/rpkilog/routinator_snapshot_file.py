from datetime import datetime, timezone
import logging
import urllib.parse
import urllib.request
from pathlib import Path

from rpkilog.data_file_super import DataFileSuper
from rpkilog.local_storage_type import LocalStorageType
from rpkilog.roa import Roa
from rpkilog.summary_file import SummaryFile

logger = logging.getLogger(__name__)


class RoutinatorSnapshotFile(DataFileSuper):
    default_filename_strftime_expression = '%Y-%m-%dT%H%M%SZ.routinator.jsonext'

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
    def fetch_from_routinator(cls, base_url: str = 'http://localhost:8323/'):
        url = base_url.rstrip('/') + '/jsonext'
        now = datetime.now(tz=timezone.utc)
        new_filename = Path(cls.default_local_storage_dir, now.strftime(cls.default_filename_strftime_expression))
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

    def iterate_roas(self):
        """
        Iterate over the ROAs contained with the file.  Yield a Roa object for each one.
        """
        if 'roas' not in self.json_data_cache:
            raise ValueError(f'"roas" key missing from JSON data')
        if not isinstance(self.json_data_cache['roas'], list):
            weirdtype = type(self.json_data_cache['roas'])
            raise TypeError(f'"roas" key within JSON data expected to be a list but it is a: {weirdtype}')
        for roa_j in self.json_data_cache['roas']:
            roa_obj = Roa.new_from_routinator_jsonext(routinator_json=roa_j, source_time=self.datetimestamp)
            yield roa_obj

    def summarize(self):
        summary = {
            'roas': []
        }
        if 'metadata' in self.json_data_cache:
            summary['metadata'] = self.json_data_cache['metadata']
        for roa_raw in self.iterate_roas():
            roa_obj = Roa.new_from_routinator_jsonext(routinator_json=roa_raw)
            roa_summarized = roa_obj.as_json_obj()
            summary['roas'].append(roa_summarized)
        return summary

    def summarize_to_file(self) -> SummaryFile:
        summary = self.summarize()
        summary_file = SummaryFile.new_from_dict(
            datetimestamp=self.datetimestamp,
            local_storage_dir=self.default_local_storage_dir,
            summary_dict=summary,
        )
        return summary_file
