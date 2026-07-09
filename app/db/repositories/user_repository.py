import uuid
from typing import Optional
from app.db.repositories.base_repository import BaseRepository
from app.models.domain.user import User

class UserRepository(BaseRepository):
    def insert(self, user: User) -> str:
        if not user.id:
            user.id = str(uuid.uuid4())
        query = "INSERT INTO users (id, tenant_id, username, role) VALUES (%s, %s, %s, %s)"
        self._execute(query, (user.id, self.tenant_id, user.username, user.role))
        return user.id

    def find_by_username(self, username: str) -> Optional[User]:
        query = "SELECT id, tenant_id, username, role, created_at FROM users WHERE username = %s AND tenant_id = %s"
        row = self._fetchone(query, (username, self.tenant_id))
        if row:
            return User(
                id=row[0],
                tenant_id=row[1],
                username=row[2],
                role=row[3],
                created_at=row[4]
            )
        return None