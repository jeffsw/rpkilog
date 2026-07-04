"""
DataFileSource: represents rows of the `source` SQL table.

TOTEST:
- test_eq_compares_column_attributes: __eq__ is True iff all column attributes match; comparison
  against a non-DataFileSource returns NotImplemented
- test_get_by_name_returns_cached_object_without_query: prepopulated cache satisfies get_by_name
  with no SQL query issued
- test_get_by_name_miss_refreshes_caches: cache miss triggers _refresh_caches(); hydrated object
  returned afterward
- test_get_by_name_unknown_raises_keyerror: name absent even after refresh raises KeyError
- test_get_by_id_returns_cached_object_without_query: as get_by_name, keyed by id
- test_get_by_id_unknown_raises_keyerror: id absent even after refresh raises KeyError
- test_refresh_caches_inserts_new_rows: rows from SELECT land in both _cache_by_id and
  _cache_by_name
- test_refresh_caches_preserves_identity_of_unchanged_rows: a cached object remains the same
  instance (is-comparison) after a refresh returning an equal row
- test_refresh_caches_updates_changed_row_in_place: a changed column (e.g. base_url) mutates the
  cached object rather than replacing it, so held references observe the change
- test_refresh_caches_rekeys_cache_by_name_on_rename: renamed row is reachable under the new name
  and the stale name key is removed
- test_invalidate_caches_empties_both_dicts: subsequent get_by_*() must re-query
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import mariadb


class DataFileSource:
    """
    Represents one row of the `source` SQL table: a producer of data files, either one of our own
    uploaders (base_url NULL) or a crawled archive site.  Rows are seeded by the initial schema
    migration; see tmp/plan/gh-81-sqldb.md for design rationale.
    """
    default_db_connection: 'mariadb.Connection' = None
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
        """
        Attributes mirror the `source` table columns.
        """
        self.id = id
        self.name = name
        self.base_url = base_url
        self.active = active
        self.notes = notes

    def __eq__(self, other) -> bool:
        """
        Equal when all `source` table column attributes match.  Used by _refresh_caches() to
        detect changed rows.
        """
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
        """
        Hash on the immutable primary key.  Defining __eq__ alone would leave the class unhashable;
        this keeps instances usable in sets and as dict keys even though non-key columns may be
        updated in place by _refresh_caches().
        """
        retval = hash(self.id)
        return retval

    @classmethod
    def get_by_name(cls, name: str, db: 'mariadb.Connection' = None) -> 'DataFileSource':
        """
        Return the DataFileSource with the given source.name (e.g. 'josephine.sobornost.net').
        This is the canonical way to hydrate a DataFileSource, e.g. for assignment to
        SnapshotSummaryFile.source.

        Consults the class caches first; on a miss, loads the whole (small) source table via
        _refresh_caches().  Raises KeyError when the name is still unknown afterward — source
        rows are seeded by schema migrations, so a miss indicates reconcile_config.yml/schema
        drift.

        db defaults to cls.default_db_connection when not supplied.
        """
        if name not in cls._cache_by_name:
            cls._refresh_caches(db=db)
        if name not in cls._cache_by_name:
            raise KeyError(f'no row in the source table has name={name!r}')
        retval = cls._cache_by_name[name]
        return retval

    @classmethod
    def get_by_id(cls, id: int, db: 'mariadb.Connection' = None) -> 'DataFileSource':
        """
        Return the DataFileSource with the given source.id.  See get_by_name() for the caching
        behavior, which is shared.

        db defaults to cls.default_db_connection when not supplied.
        """
        if id not in cls._cache_by_id:
            cls._refresh_caches(db=db)
        if id not in cls._cache_by_id:
            raise KeyError(f'no row in the source table has id={id!r}')
        retval = cls._cache_by_id[id]
        return retval

    @classmethod
    def _refresh_caches(cls, db: 'mariadb.Connection' = None):
        """
        Load every row of the source table and merge them into the class caches, keyed by id and
        by name.  Loading the whole table on any cache miss may seem counter-intuitive, but the
        table is small, so this minimizes database traffic and program latency while maintaining
        correctness.

        Newly-discovered rows are inserted into both caches.  A row equal (__eq__) to its cached
        entry is ignored, so the cached object keeps its identity.  A row differing from its
        cached entry updates that object's attributes in place — references held elsewhere (e.g.
        SnapshotSummaryFile.source) observe the change — and if the name changed, _cache_by_name
        is re-keyed.

        db defaults to cls.default_db_connection when not supplied.
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
        """
        Empty the by-id and by-name caches, forcing the next get_by_*() to re-query the source
        table.  Not expected to be needed in practice; it mostly documents how the caching works.
        """
        cls._cache_by_id = {}
        cls._cache_by_name = {}
