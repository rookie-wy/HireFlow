import chromadb
from chromadb.config import Settings as ChromaSettings
from app.core.config import settings

_vector_client = None

def get_chroma_client() -> chromadb.HttpClient:
    global _vector_client
    if _vector_client is None:
        _vector_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
    return _vector_client

def get_collection(name: str):
    client = get_chroma_client()
    return client.get_or_create_collection(name=name)