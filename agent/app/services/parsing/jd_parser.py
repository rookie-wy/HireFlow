"""JD 解析：LLM 抽取结构化岗位描述。"""
from __future__ import annotations

from typing import List, Optional

from app.core.errors import BadRequestError, LLMError, get_logger
from app.infra.llm_client import get_llm_client
from app.infra.pii import mask_id_card
from app.services.parsing.schemas import JobDescription

log = get_logger(__name__)

JD_PROMPT = """你是一名资深招聘专家。请从以下职位描述中抽取结构化信息，返回严格 JSON 格式：
{{
  "title": "职位名称",
  "hard_requirements": ["硬性要求，如学历/年限/必备技能"],
  "soft_requirements": ["软性要求，如沟通能力/团队协作"],
  "skill_graph": ["核心技能标签列表"],
  "job_category": "岗位类别，必须是 tech | management | design | general 之一"
}}

职位描述：
{jd_text}"""


def parse_jd(jd_text: str, language: str = "zh") -> JobDescription:
    """解析 JD；解析失败抛 LLMError（backend 层可感知重试）。"""
    if not jd_text or not jd_text.strip():
        raise BadRequestError("jd_text 不能为空")

    cleaned = mask_id_card(jd_text[:20000])
    client = get_llm_client()
    messages = [
        {"role": "system", "content": "你是一个精确的信息抽取引擎，只输出 JSON。"},
        {"role": "user", "content": JD_PROMPT.format(jd_text=cleaned)},
    ]
    try:
        data, usage = client.chat_json(messages, temperature=0.0, max_tokens=1500)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMError(cause=exc) from exc

    parsed = JobDescription(
        title=str(data.get("title") or "未命名岗位"),
        hard_requirements=_str_list(data.get("hard_requirements")),
        soft_requirements=_str_list(data.get("soft_requirements")),
        skill_graph=_str_list(data.get("skill_graph")),
        job_category=_category(data.get("job_category")),
    )
    log.info("jd parsed: title=%s category=%s tokens=%d", parsed.title, parsed.job_category,
             usage.tokens_prompt + usage.tokens_completion)
    return parsed


def _str_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _category(value) -> str:
    cat = str(value or "").lower().strip()
    return cat if cat in {"tech", "management", "design", "general"} else "general"
