import datetime

import pydantic
import yaml

from rpkilog.build_machine_to_source_mapping import BuildMachineToSourceMapping


class ReconcileConfig(pydantic.BaseModel):
    """
    Reconciler configuration, normally hydrated from the packaged reconcile_config.yml data file.
    """
    buildmachine_to_source: list[BuildMachineToSourceMapping]

    @classmethod
    def load(cls, yaml_str: str) -> 'ReconcileConfig':
        """
        Hydrate a ReconcileConfig from a YAML document given as a string.
        """
        config_data = yaml.safe_load(yaml_str)
        retval = cls(**config_data)
        return retval

    def get_source_name(self, buildmachine: str, observation_datetime: datetime.datetime) -> str:
        """
        Return the `source` name for a data file, using the ordered buildmachine_to_source list:
        the first mapping whose matches() returns True wins.

        TODO: implement; decide behavior when no mapping matches — such a file can't be keyed in
          data_file (raise ValueError here and let the caller decide skip-and-warn vs abort?)
        """
        pass
