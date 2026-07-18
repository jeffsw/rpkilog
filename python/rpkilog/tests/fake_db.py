"""
Minimal stand-ins for a mariadb connection/cursor, for tests of the SQL-row methods; no MariaDB
server needed.  Executed statements are recorded on the FakeDb; rows a cursor returns are
configured per statement fragment.
"""


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self._rows = []

    def execute(self, statement, params=None):
        self.db.executed.append((statement, params))
        self._rows = self.db.rows_for(statement)

    def fetchone(self):
        if self._rows:
            retval = self._rows[0]
        else:
            retval = None
        return retval

    def fetchall(self):
        return self._rows

    def close(self):
        self.db.closed_cursor_count += 1


class FakeDb:
    """
    rows_by_fragment maps a distinctive substring of an SQL statement to the rows a cursor
    returns for it; statements matching no fragment return no rows.  Every executed
    (statement, params) pair is recorded in self.executed.
    """
    def __init__(self, rows_by_fragment: dict = None):
        self.executed = []
        self.closed_cursor_count = 0
        if rows_by_fragment is None:
            rows_by_fragment = {}
        self.rows_by_fragment = rows_by_fragment

    def cursor(self, **kwargs):
        retval = FakeCursor(self)
        return retval

    def rows_for(self, statement: str) -> list:
        for fragment, rows in self.rows_by_fragment.items():
            if fragment in statement:
                return rows
        return []
