from datetime import datetime
from pathlib import Path

from rpkilog.data_file_super import DataFileSuper
from rpkilog.local_storage_type import LocalStorageType
from rpkilog.vrp_diff import VrpDiff


class DiffFile(DataFileSuper):
    default_filename_strftime_expression = '%Y-%m-%dT%H%M%SZ.vrpdiff.json'

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
        pass

    def iterate_diffs(self):
        """
        Caller may use this to iterate over the vrp_diffs list-entries contained within the file.
        Yields a series of VrpDiff objects.

        See also: VrpDiff.from_json_obj()
        """
        if 'vrp_diffs' not in self.json_data_cache:
            raise ValueError(f'"vrp_diffs" key missing from JSON data: {self}')
        if not isinstance(self.json_data_cache['vrp_diffs'], list):
            weirdtype = type(self.json_data_cache['vrp_diffs'])
            raise TypeError(f'"vrp_diffs" key within JSON data expected to be a list but it is a: {weirdtype}')
        for diff_entry_j in self.json_data_cache['vrp_diffs']:
            diff_entry_obj = VrpDiff.from_json_obj(j=diff_entry_j)
            yield diff_entry_obj

    @classmethod
    def new_from_path(
            cls,
            path: Path,
            datetimestamp: datetime = None,
            local_storage_type: LocalStorageType = LocalStorageType.UNSPECIFIED,
    ):
        """
        Instantiate an object given a path to a local diff file.

        If no datetimestamp is provided, we attempt to parse that from the filename using a regex.  If
        this fails, a ValueError is raised.  ALL FILENAME-BASED TIMESTAMPS ASSUMED TO BE UTC.
        TODO: This indicates a need for better in-file metadata.  There is a `timestamp` in the metadata
              but it is the time the diff was generated, not the observed time of the diffs, which should
              be the timestamp of the *new* VRP cache used to produce the diff.
              That is in the metadata also as metadata->vrp_cache_new->filename but probably less-guaranteed.
              There is also metadata->vrp_cache_new->metadata->buildtime but not for routinator.
              Needs work.

        If local_storage_type is LocalStorageType.UNSPECIFIED the file will be examined to determine if
        it's a plain JSON or BZ2 file.  If it seems to be neither of those types, a ValueError is raised.
        """
        if not datetimestamp:
            datetimestamp = cls.infer_datetimestamp_from_path(path)
        constructor_args = {
            'datetimestamp': datetimestamp,
            'local_storage_type': local_storage_type,
        }
        match local_storage_type:
            case LocalStorageType.UNCOMPRESSED:
                constructor_args['local_filepath_uncompressed'] = path
            case LocalStorageType.BZIP2:
                constructor_args['local_filepath_bz2'] = path

        retobj = cls(**constructor_args)
        if local_storage_type == LocalStorageType.UNSPECIFIED:
            retobj.infer_local_storage_type(path)

        return retobj
