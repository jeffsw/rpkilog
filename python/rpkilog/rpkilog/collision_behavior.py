from enum import StrEnum


class CollisionBehavior(StrEnum):
    OVERWRITE = 'overwrite'
    """If there is a pre-existing object, overwrite it with the new one."""

    RETAIN = 'retain'
    """If there is a pre-existing object, retain that existing one."""
