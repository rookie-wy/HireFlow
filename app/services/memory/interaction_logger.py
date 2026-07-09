import uuid
from datetime import datetime
from app.db.repositories.interaction_repository import InteractionRepository
from app.db.session import get_db
from app.services.parsing.vectorization import embed_texts  # 重用文本嵌入
from app.infrastructure.chroma_client import get_collection

class InteractionLogger:
    @staticmethod
    def log_event(tenant_id: str, session_id: str, user_id: str, event_type: str,
                  target_id: str = None, feedback: str = None, summary_text: str = None):
        summary_vector_id = None
        if summary_text:
            # 向量化并存入ChromaDB的interaction_summaries集合
            emb = embed_texts([summary_text])[0]
            vector_id = str(uuid.uuid4())
            collection = get_collection("interaction_summaries")
            collection.add(
                ids=[vector_id],
                embeddings=[emb],
                documents=[summary_text],
                metadatas=[{"tenant_id": tenant_id, "target_id": target_id, "event_type": event_type}]
            )
            summary_vector_id = vector_id

        with get_db() as conn:
            repo = InteractionRepository(conn)
            repo.insert(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                target_id=target_id,
                feedback=feedback,
                summary_vector_id=summary_vector_id,
                created_at=datetime.utcnow()
            )