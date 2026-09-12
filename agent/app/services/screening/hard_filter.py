"""硬性条件过滤：学历 / 年限 / 技能三维度规则（修复旧版仅学历的缺口）。"""
from __future__ import annotations

import datetime
import re
from typing import List, Sequence

from app.core.errors import get_logger

log = get_logger(__name__)

_EDU_RANK = {"专科": 1, "本科": 2, "硕士": 3, "研究生": 3, "博士": 4}
_EDU_KEYWORDS = [
    ("博士", 4), ("硕士", 3), ("研究生", 3), ("本科", 2), ("专科", 1),
]

_YEAR_RE = re.compile(r"(\d+)\s*年")
_YEARS = "years_of_experience"

# 英文/缩写技能用词边界匹配，避免 "Java" 命中 "JavaScript"、"C" 命中 "CSS" 这类子串误判
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def skill_hit(tag: str, skills: set[str], text: str) -> bool:
    """技能命中判定（单一入口，供硬过滤与粗筛复用）。

    - 结构化技能标签列表：英文做**精确匹配**（已标准化，无需子串）；
      中文标签保留子串匹配（"机器学习" 可能是 "机器学习平台" 的一部分）。
    - 简历原文：英文技能用**词边界正则**（Java 不匹配 JavaScript；C++ / Node.js / CI/CD
      这类含符号的标签按字面转义后同样加边界），中文技能仍用子串。
    """
    tag = (tag or "").strip()
    if not tag:
        return False
    low = tag.lower()
    if low in skills:
        return True
    if _CJK_RE.search(tag):
        return any(low in s for s in skills) or low in text
    pattern = re.compile(r"(?<![a-z0-9+#.])" + re.escape(low) + r"(?![a-z0-9+#])")
    if any(pattern.search(s) for s in skills):
        return True
    return bool(pattern.search(text))


def _current_year() -> int:
    """当前年份（不再硬编码，跨年后年限判定不会悄悄偏一年）。"""
    return datetime.date.today().year


def required_degree(hard_requirements: Sequence[str]) -> int:
    """从硬性要求中解析最低学历要求，返回学历等级（0 表示无要求）。"""
    level = 0
    for req in hard_requirements:
        if not isinstance(req, str):
            continue
        for kw, lv in _EDU_KEYWORDS:
            if kw in req:
                level = max(level, lv)
                # “XX及以上”明确化；未写明时默认就是该等级
    return level


def candidate_degree(structured: dict) -> int:
    best = 0
    for edu in structured.get("education") or []:
        degree = str((edu or {}).get("degree") or "")
        for name, lv in _EDU_RANK.items():
            if name in degree:
                best = max(best, lv)
    return best


def required_years(hard_requirements: Sequence[str]) -> int:
    for req in hard_requirements:
        m = _YEAR_RE.search(str(req or ""))
        if m:
            return int(m.group(1))
    return 0


def candidate_years(structured: dict) -> int:
    """按工作经历估算年限（同段时间不重复计；在职/至今按当前年份计）。"""
    spans = []
    now_year = _current_year()
    for w in structured.get("work_experience") or []:
        start = str((w or {}).get("start_date") or "")
        end = str((w or {}).get("end_date") or "至今")
        start_year = _year(start)
        end_year = _year(end) if end and _year(end) else now_year
        if start_year:
            spans.append((start_year, max(end_year, start_year)))
    if not spans:
        return 0
    spans.sort()
    total = 0
    cur_start, cur_end = spans[0]
    for s, e in spans[1:]:
        if s > cur_end:
            total += cur_end - cur_start
            cur_start, cur_end = s, e
        else:
            cur_end = max(cur_end, e)
    total += cur_end - cur_start
    return max(total, 0)


def _year(date_str: str) -> int:
    m = re.search(r"(20\d{2}|19\d{2})", str(date_str or ""))
    return int(m.group(1)) if m else 0


def required_skills(hard_requirements: Sequence[str]) -> List[str]:
    """抽取硬性要求中出现的具体技能词（与 skill_graph 的交集在调用方完成）。"""
    skills: List[str] = []
    for req in hard_requirements:
        text = str(req or "")
        if not text:
            continue
        # 粗提取：英文词与常见技术名词
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+#./]{1,30}", text):
            if token.lower() in {"年", "经验", "以上", "优先"}:
                continue
            skills.append(token)
    return skills


def hard_filter(
    hard_requirements: List[str],
    skill_graph: List[str],
    candidates: List[dict],
) -> List[dict]:
    """过滤候选人列表，返回通过者。

    candidates: [{candidate_id, resume_text, structured_json}]
    规则（全部维度可豁免：JD 未提及时不限制）：
      - 学历：candidate_degree >= required_degree
      - 年限：candidate_years >= required_years（要求>0 时）
      - 技能：硬性要求中提到的技能（与 skill_graph 交集）至少命中 1 个
    """
    need_degree = required_degree(hard_requirements)
    need_years = required_years(hard_requirements)
    graph = {s.lower() for s in (skill_graph or [])}
    need_skills = [s for s in required_skills(hard_requirements) if s.lower() in graph]

    passed: List[dict] = []
    for cand in candidates:
        structured = cand.get("structured_json") or {}
        if need_degree and candidate_degree(structured) < need_degree:
            continue
        if need_years and candidate_years(structured) < need_years:
            continue
        if need_skills:
            cand_skills = {str(s).strip().lower() for s in structured.get("skills") or []}
            resume_text = str(cand.get("resume_text") or "").lower()
            # 词边界匹配：避免 Java↔JavaScript、C↔CSS 这类子串误判（此前会把前端候选人放进 Java 岗位）
            if not any(skill_hit(s, cand_skills, resume_text) for s in need_skills):
                continue
        passed.append(cand)

    log.info(
        "hard filter: %d/%d passed (degree>=%d, years>=%d, skills=%s)",
        len(passed), len(candidates), need_degree, need_years, need_skills,
    )
    return passed
