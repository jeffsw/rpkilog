import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import mariadb


class DataFileType:
    """
    Represents one row of the `file_type` SQL table: a (kind, version) lookup describing the
    format of an underlying data file, e.g. name='rpkiclient_snapshot_summary_v1' kind='summary'.
    A new format revision is a new row; rows referencing a deprecated_at format are the
    reprocessing/upgrade backlog.  See the file_type decision in tmp/plan/gh-81-sqldb.md.
    """
    default_db_connection: 'mariadb.SyncConnection' = None

    def __init__(
            self,
            id: int,
            kind: str,
            name: str,
            description: str = None,
            deprecated_at: datetime.datetime = None,
    ):
        """
        Attributes mirror the `file_type` table columns.

        TODO: consider a Python Enum mirroring the SQL ENUM('full','summary','diff') for kind
        """
        self.id = id
        self.kind = kind
        self.name = name
        self.description = description
        self.deprecated_at = deprecated_at

    @classmethod
    def get_by_name(cls, name: str, db: 'mariadb.SyncConnection' = None) -> 'DataFileType':
        """
        Retrieve the row with the given file_type.name (e.g. SnapshotSummaryFile.sql_file_type_name)
        and return it as a DataFileType.

        db defaults to cls.default_db_connection when not supplied.

        TODO: SELECT id, kind, name, description, deprecated_at FROM file_type WHERE name = ?
        TODO: raise when no row matches (formats are seeded/added by schema migrations)
        """
        pass
