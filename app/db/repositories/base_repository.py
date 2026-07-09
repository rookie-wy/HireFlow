from app.core.context import tenant_id_var

class BaseRepository:
    def __init__(self, conn):
        self.conn = conn
        self.cursor = conn.cursor()

    @property
    def tenant_id(self):
        return tenant_id_var.get()

    def _execute(self, query, params=None):
        self.cursor.execute(query, params)

    def _fetchone(self, query, params=None):
        self._execute(query, params)
        return self.cursor.fetchone()

    def _fetchall(self, query, params=None):
        self._execute(query, params)
        return self.cursor.fetchall()