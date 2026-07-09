import logging
from app.infrastructure.chroma_client import get_collection
from app.infrastructure.models.embedding_client import embed_texts

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500
OVERLAP = 50

def chunk_text(text: str, chunk_size=CHUNK_SIZE, overlap=OVERLAP):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks

def vectorize_candidate(candidate_id: str, tenant_id: str, resume_text: str):
    collection = get_collection("resumes")
    chunks = chunk_text(resume_text)
    if not chunks:
        return
    embeddings = embed_texts(chunks)
    if embeddings is None:
        logger.warning("Embedding model unavailable, skipping vectorization")
        return
    ids = [f"{candidate_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {"tenant_id": tenant_id, "candidate_id": candidate_id, "chunk_index": i}
        for i in range(len(chunks))
    ]
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas
    )
    logger.info(f"Vectorized candidate {candidate_id} with {len(chunks)} chunks")