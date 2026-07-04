import datetime
import re

import pydantic


class BuildMachineToSourceMapping(pydantic.BaseModel):
    """
    Maps buildmachine hostnames appearing in snapshot-summary metadata to a source name.

    A mapping applies to summaries whose buildtime falls within [datetime_start, datetime_end]
    (inclusive of both ends) and whose buildmachine matches any of the given regex patterns.
    """
    datetime_start: datetime.datetime
    datetime_end: datetime.datetime
    regex: list[re.Pattern]
    name: str
    comment: str | None = None

    def matches(self, buildmachine: str, observation_datetime: datetime.datetime) -> bool:
        """
        Return True if observation_datetime falls within [datetime_start, datetime_end]
        (inclusive of both ends) and buildmachine matches any of self.regex.
        """
        retval = False
        if self.datetime_start <= observation_datetime <= self.datetime_end:
            for pattern in self.regex:
                if pattern.search(buildmachine):
                    retval = True
                    break
        return retval
