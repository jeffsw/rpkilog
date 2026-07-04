import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import mariadb


class DataFileType:
    """
    One row of the `file_type` SQL table: a (kind, version) lookup describing the format of an
    underlying data file, e.g. name='rpkiclient_snapshot_summary_v1' kind='summary'.
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
        # TODO: consider a Python Enum mirroring the SQL ENUM('full','summary','diff') for kind
        self.id = id
        self.kind = kind
        self.name = name
        self.description = description
        self.deprecated_at = deprecated_at

    @classmethod
    def get_by_name(cls, name: str, db: 'mariadb.SyncConnection' = None) -> 'DataFileType':
        """
        Return the DataFileType with the given file_type.name.  Raises KeyError for an unknown name.

        TOTEST (fake db cursor):
        - test_get_by_name_hydrates_from_row
        - test_get_by_name_unknown_raises_keyerror
        - test_get_by_name_uses_default_db_connection
        """
        if db is None:
            db = cls.default_db_connection
        cursor = db.cursor(named_tuple=True)
        try:
            cursor.execute(
                'SELECT id, kind, name, description, deprecated_at FROM file_type WHERE name = ?',
                (name,),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KeyError(f'no row in the file_type table has name={name!r}')
        retval = cls(
            id=row.id,
            kind=row.kind,
            name=row.name,
            description=row.description,
            deprecated_at=row.deprecated_at,
        )
        return retval
