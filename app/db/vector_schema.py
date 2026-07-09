# ChromaDB 逻辑定义（无客户端依赖，纯配置）
from pydantic import BaseModel
from typing import List

class VectorCollectionConfig:
    COLLECTION_RESUMES = "resumes"
    COLLECTION_JOB_SUMMARIES = "job_summaries"
    COLLECTION_INTERACTION_SUMMARIES = "interaction_summaries"
    VECTOR_DIM = 1024  # BGE-M3 output dimension
    METADATA_FIELDS = ["tenant_id", "candidate_id", "job_id", "chunk_index"]