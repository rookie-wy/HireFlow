import uuid
from typing import Optional
from app.db.repositories.base_repository import BaseRepository
from app.models.domain.user import User

class UserRepository(BaseRepository):
    def insert(self, user: User) -> str:
        if not user.id:
            user.id = str(uuid.uuid4())
        query = "INSERT INTO users (id, tenant_id, username, password_hash, role) VALUES (%s, %s, %s, %s, %s)"
        self._execute(query, (user.id, user.tenant_id or self.tenant_id, user.username, user.password_hash, user.role))
        return user.id

    def find_by_username(self, username: str, tenant_id: str = None) -> Optional[User]:
        tid = tenant_id or self.tenant_id
        query = "SELECT id, tenant_id, username, password_hash, role, created_at FROM users WHERE username = %s AND tenant_id = %s"
        row = self._fetchone(query, (username, tid))
        if row:
            return User(
                id=row[0],
                tenant_id=row[1],
                username=row[2],
                password_hash=row[3],
                role=row[4],
                created_at=row[5]
            )
        return None