"""
DataFileSource: represents rows of the `source` SQL table.

TOTEST:
- test_eq_compares_column_attributes
- test_get_by_name_returns_cached_object_without_query
- test_get_by_name_miss_refreshes_caches
- test_get_by_name_unknown_raises_keyerror
- test_get_by_id_returns_cached_object_without_query
- test_get_by_id_unknown_raises_keyerror
- test_get_all_refreshes_and_sorts_by_id
- test_refresh_caches_inserts_new_rows
- test_refresh_caches_preserves_identity_of_unchanged_rows
- test_refresh_caches_updates_changed_row_in_place
- test_refresh_caches_rekeys_cache_by_name_on_rename
- test_invalidate_caches_empties_both_dicts
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import mariadb


class DataFileSource:
    """
    One row of the `source` SQL table: a producer of data files, either one of our own uploaders
    (base_url NULL) or a crawled archive site.
    """
    default_db_connection: 'mariadb.SyncConnection' = None
    _cache_by_id: dict[int, 'DataFileSource'] = {}
    _cache_by_name: dict[str, 'DataFileSource'] = {}

    def __init__(
            self,
            id: int,
            name: str,
            base_url: str = None,
            active: bool = True,
            notes: str = None,
    ):
        self.id = id
        self.name = name
        self.base_url = base_url
        self.active = active
        self.notes = notes

    def __eq__(self, other) -> bool:
        if not isinstance(other, DataFileSource):
            retval = NotImplemented
        else:
            retval = (
                self.id == other.id
                and self.name == other.name
                and self.base_url == other.base_url
                and self.active == other.active
                and self.notes == other.notes
            )
        return retval

    def __hash__(self):
        # hash only the immutable PK; non-key columns may be updated in place by _refresh_caches()
        retval = hash(self.id)
        return retval

    @classmethod
    def get_by_name(cls, name: str, db: 'mariadb.SyncConnection' = None) -> 'DataFileSource':
        """
        Return the DataFileSource with the given source.name, from cache or the database.
        Raises KeyError for an unknown name.
        """
        if name not in cls._cache_by_name:
            cls._refresh_caches(db=db)
        if name not in cls._cache_by_name:
            raise KeyError(f'no row in the source table has name={name!r}')
        retval = cls._cache_by_name[name]
        return retval

    @classmethod
    def get_by_id(cls, id: int, db: 'mariadb.SyncConnection' = None) -> 'DataFileSource':
        """
        Return the DataFileSource with the given source.id, from cache or the database.
        Raises KeyError for an unknown id.
        """
        if id not in cls._cache_by_id:
            cls._refresh_caches(db=db)
        if id not in cls._cache_by_id:
            raise KeyError(f'no row in the source table has id={id!r}')
        retval = cls._cache_by_id[id]
        return retval

    @classmethod
    def get_all(cls, db: 'mariadb.SyncConnection' = None) -> list['DataFileSource']:
        """
        Return every row of the source table as DataFileSource objects, sorted by id.  Always
        refreshes the caches first, so rows added since the last query are included.
        """
        cls._refresh_caches(db=db)
        retlist = []
        for id in sorted(cls._cache_by_id):
            retlist.append(cls._cache_by_id[id])
        return retlist

    @classmethod
    def _refresh_caches(cls, db: 'mariadb.SyncConnection' = None):
        """
        Load the whole (small) source table into the class caches.  Changed rows update the
        cached object in place, so references held elsewhere observe the change.
        """
        if db is None:
            db = cls.default_db_connection
        cursor = db.cursor(named_tuple=True)
        try:
            cursor.execute('SELECT id, name, base_url, active, notes FROM source')
            rows = cursor.fetchall()
        finally:
            cursor.close()
        for row in rows:
            discovered = cls(
                id=row.id,
                name=row.name,
                base_url=row.base_url,
                active=bool(row.active),
                notes=row.notes,
            )
            cached = cls._cache_by_id.get(discovered.id)
            if cached is None:
                cls._cache_by_id[discovered.id] = discovered
                cls._cache_by_name[discovered.name] = discovered
            elif cached != discovered:
                if cached.name != discovered.name:
                    del cls._cache_by_name[cached.name]
                    cls._cache_by_name[discovered.name] = cached
                cached.name = discovered.name
                cached.base_url = discovered.base_url
                cached.active = discovered.active
                cached.notes = discovered.notes

    @classmethod
    def invalidate_caches(cls):
        cls._cache_by_id = {}
        cls._cache_by_name = {}
