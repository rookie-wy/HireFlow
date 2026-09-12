"""技能标准化：18 个标准标签，语义匹配优先（嵌入相似度>0.7），规则匹配后备。"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.core.errors import get_logger

log = get_logger(__name__)

STANDARD_SKILL_TAGS = [
    "Python", "Java", "Go", "C++", "Rust",
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
    "Product Management", "Agile", "Scrum", "Sales", "Marketing", "SaaS",
    "UI/UX Design", "Graphic Design", "SQL",
]

# 同义词表（规则匹配的第一优先级）
_ALIASES: Dict[str, str] = {
    "py": "Python", "python3": "Python", "django": "Python", "flask": "Python",
    "fastapi": "Python", "pandas": "Python", "numpy": "Python",
    "java": "Java", "spring": "Java", "springboot": "Java", "j2ee": "Java",
    "golang": "Go", "go": "Go",
    "cpp": "C++", "c/c++": "C++", "c plus plus": "C++",
    "rust": "Rust",
    "ml": "Machine Learning", "machinelearning": "Machine Learning",
    "机器学习": "Machine Learning",
    "dl": "Deep Learning", "deeplearning": "Deep Learning", "深度学习": "Deep Learning",
    "nlp": "NLP", "自然语言处理": "NLP",
    "cv": "Computer Vision", "computervision": "Computer Vision", "计算机视觉": "Computer Vision",
    "pm": "Product Management", "productmanager": "Product Management", "产品经理": "Product Management",
    "agile": "Agile", "敏捷": "Agile",
    "scrum": "Scrum",
    "sales": "Sales", "销售": "Sales",
    "marketing": "Marketing", "市场营销": "Marketing",
    "saas": "SaaS",
    "ui": "UI/UX Design", "ux": "UI/UX Design", "ui/ux": "UI/UX Design", "uiux": "UI/UX Design",
    "ui设计": "UI/UX Design",
    "graphic design": "Graphic Design", "平面设计": "Graphic Design",
    "sql": "SQL", "mysql": "SQL", "postgresql": "SQL",
}

_SIM_THRESHOLD = 0.7

# 标准标签向量的进程内缓存（18 个常量，避免每次上传重复嵌入）
_TAG_VECS: Optional[List[List[float]]] = None


def match_skills(raw_skills: List[str]) -> List[str]:
    """原始技能 → 标准标签。两阶段：规则别名优先（精确），剩余走语义匹配（降级安全）。"""
    if not raw_skills:
        return []
    normalized = [str(s).strip() for s in raw_skills if str(s).strip()]

    out: List[str] = []
    unmatched: List[str] = []
    for skill in normalized:
        mapped = _rule_map_one(skill)
        if mapped is not None:
            out.append(mapped)
        else:
            unmatched.append(skill)
            out.append(skill)  # 先占位，语义阶段可能覆盖

    if unmatched:
        semantic = _semantic_match(unmatched)
        if semantic is not None:
            sem_map = dict(zip(unmatched, semantic))
            out = [sem_map.get(s, s) for s in out]
    return _dedupe(out)


def _rule_map_one(skill: str) -> Optional[str]:
    """单条规则映射；命中标准标签或别名返回标准标签，否则 None。"""
    if skill in STANDARD_SKILL_TAGS:
        return skill
    lower = skill.lower().strip()
    if lower in STANDARD_SKILL_TAGS:
        return STANDARD_SKILL_TAGS[STANDARD_SKILL_TAGS.index(lower)]
    key = lower.replace(" ", "")
    if key in _ALIASES:
        return _ALIASES[key]
    for alias, tag in _ALIASES.items():
        if len(alias) >= 3 and (alias in key or key in alias):
            return tag
    return None


def _rule_based_match(skills: List[str]) -> List[str]:
    out: List[str] = []
    for skill in skills:
        key = skill.lower().replace(" ", "")
        if skill in STANDARD_SKILL_TAGS:
            out.append(skill)
        elif skill.lower() in STANDARD_SKILL_TAGS:
            out.append(STANDARD_SKILL_TAGS[STANDARD_SKILL_TAGS.index(skill.lower())])
        elif key in _ALIASES:
            out.append(_ALIASES[key])
        elif skill.lower() in _ALIASES:
            out.append(_ALIASES[skill.lower()])
        else:
            # 子串包含
            for alias, tag in _ALIASES.items():
                if alias in key or key in alias:
                    out.append(tag)
                    break
            else:
                out.append(skill)  # 保留原文
    return _dedupe(out)


def _tag_vectors() -> Optional[List[List[float]]]:
    """标准标签向量：进程内缓存（18 个常量，没必要每次上传重算）。"""
    global _TAG_VECS
    if _TAG_VECS is None:
        from app.infra.embedding_client import embed_texts

        _TAG_VECS = embed_texts(STANDARD_SKILL_TAGS)
        if _TAG_VECS is not None:
            log.info("skill tag vectors cached (n=%d)", len(_TAG_VECS))
    return _TAG_VECS


def embedding_texts_for_skills(skills: List[str]) -> List[str]:
    """供调用方把「技能 + 其他文本」合并成一次批量嵌入（见 resume_parser）。"""
    return list(dict.fromkeys([str(s).strip() for s in skills if str(s).strip()]))


def _semantic_match(skills: List[str]) -> Optional[List[str]]:
    """标准标签与原始技能互相算余弦相似度。嵌入不可用时返回 None。

    性能：标签向量走进程缓存（此前每次上传都重新嵌入 18 个常量标签），
    技能向量单独一次批量嵌入。
    """
    try:
        from app.infra.embedding_client import embed_backend, embed_texts

        embed_backend()  # 触发加载，失败抛异常
        tag_vecs = _tag_vectors()
        skill_vecs = embed_texts(skills)
        if tag_vecs is None or skill_vecs is None:
            return None

        import numpy as np

        tag_mat = np.array(tag_vecs, dtype="float32")
        skill_mat = np.array(skill_vecs, dtype="float32")
        tag_mat /= (np.linalg.norm(tag_mat, axis=1, keepdims=True) + 1e-9)
        skill_mat /= (np.linalg.norm(skill_mat, axis=1, keepdims=True) + 1e-9)
        sim = skill_mat @ tag_mat.T  # (n_skills, n_tags)

        out: List[str] = []
        for i, skill in enumerate(skills):
            best = int(sim[i].argmax())
            if float(sim[i][best]) > _SIM_THRESHOLD:
                out.append(STANDARD_SKILL_TAGS[best])
            else:
                out.append(skill)
        return _dedupe(out)
    except Exception as exc:  # noqa: BLE001
        log.warning("semantic skill match unavailable (%s), fallback to rules", exc)
        return None


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out
