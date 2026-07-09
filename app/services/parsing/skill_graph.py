import logging
from typing import List
import numpy as np

logger = logging.getLogger(__name__)

STANDARD_SKILL_TAGS = [
    "Python", "Java", "Go", "C++", "Rust",
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
    "Project Management", "Agile", "Scrum",
    "Sales", "Marketing", "SaaS",
    "UI/UX Design", "Graphic Design",
]

# 嵌入向量缓存
_tag_embeddings = None

def _init_embeddings():
    """尝试初始化标准标签嵌入，失败则置为 None"""
    global _tag_embeddings
    try:
        from app.infrastructure.models.embedding_client import embed_texts
        embeddings = embed_texts(STANDARD_SKILL_TAGS)
        if embeddings is not None:
            _tag_embeddings = embeddings
            logger.info("Skill embeddings initialized")
        else:
            _tag_embeddings = None
            logger.warning("Embedding model unavailable, will use rule-based matching")
    except Exception as e:
        _tag_embeddings = None
        logger.warning(f"Embedding init failed: {e}")

def match_skills(raw_skills: List[str]) -> List[str]:
    """
    技能匹配：优先使用语义匹配（若嵌入可用），否则降级为规则匹配。
    """
    if _tag_embeddings is None:
        _init_embeddings()

    if _tag_embeddings is not None and raw_skills:
        # 语义匹配模式
        from app.infrastructure.models.embedding_client import embed_texts
        raw_embs = embed_texts(raw_skills)
        if raw_embs is None:
            # 嵌入调用失败，降级
            return _rule_based_match(raw_skills)

        matched = set()
        for raw_emb in raw_embs:
            sims = np.dot(_tag_embeddings, raw_emb) / (
                np.linalg.norm(_tag_embeddings, axis=1) * np.linalg.norm(raw_emb)
            )
            best_idx = np.argmax(sims)
            if sims[best_idx] > 0.7:
                matched.add(STANDARD_SKILL_TAGS[best_idx])
            else:
                # 相似度不够，保留原始技能
                orig_skill = raw_skills[raw_embs.index(raw_emb)]
                matched.add(orig_skill)
        return list(matched)
    else:
        # 降级为规则匹配
        return _rule_based_match(raw_skills)

def _rule_based_match(raw_skills: List[str]) -> List[str]:
    """纯规则匹配（大小写不敏感、部分包含）"""
    matched = set()
    for skill in raw_skills:
        # 精确匹配
        if skill in STANDARD_SKILL_TAGS:
            matched.add(skill)
        else:
            lower_skill = skill.lower()
            found = False
            for tag in STANDARD_SKILL_TAGS:
                if tag.lower() == lower_skill:
                    matched.add(tag)
                    found = True
                    break
            if not found:
                for tag in STANDARD_SKILL_TAGS:
                    if tag.lower() in lower_skill or lower_skill in tag.lower():
                        matched.add(tag)
                        found = True
                        break
            if not found:
                matched.add(skill)
    return list(matched)