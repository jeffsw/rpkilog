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

        Raises KeyError when no mapping matches — such a file can't be keyed in data_file; the
        caller decides skip-and-warn (the reconciler counts it UNATTRIBUTABLE) vs abort.

        TOTEST:
        - test_get_source_name_first_match_wins: with two mappings matching the same
          buildmachine, the earlier mapping's name is returned
        - test_get_source_name_respects_datetime_range: a buildmachine-matching mapping is
          skipped when observation_datetime falls outside its datetime range
        - test_get_source_name_no_match_raises_keyerror
        """
        for mapping in self.buildmachine_to_source:
            if mapping.matches(buildmachine=buildmachine, observation_datetime=observation_datetime):
                retstr = mapping.name
                return retstr
        raise KeyError(
            f'no buildmachine_to_source mapping matches buildmachine={buildmachine!r} '
            f'at {observation_datetime}'
        )
