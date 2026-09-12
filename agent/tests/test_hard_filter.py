"""硬性过滤单测：技能词边界、中文技能、年限计算、学历门槛。

重点防回归：Java 不能命中 JavaScript（曾把前端候选人放进 Java 岗位）。
"""
from __future__ import annotations

import datetime

from app.services.screening.hard_filter import (
    candidate_degree,
    candidate_years,
    hard_filter,
    required_degree,
    required_skills,
    required_years,
    skill_hit,
)


def _cand(cid: str, skills: list[str], text: str = "", work: list[dict] | None = None,
          edu: list[dict] | None = None) -> dict:
    structured: dict = {"skills": skills}
    if work:
        structured["work_experience"] = work
    if edu:
        structured["education"] = edu
    return {"candidate_id": cid, "resume_text": text, "structured_json": structured}


# ---------- 技能词边界 ----------
def test_english_skill_uses_word_boundary():
    """Java 不应命中 JavaScript；C 不应命中 CSS / CD。"""
    assert skill_hit("Java", {"javascript", "react"}, "熟练 javascript/typescript") is False
    assert skill_hit("Java", {"java"}, "java 后端") is True
    assert skill_hit("C", {"css"}, "写过 css") is False
    assert skill_hit("C", {"c"}, "") is True


def test_symbol_skills_match_literally():
    """C++ / CI/CD / Node.js 这类含符号的技能按字面匹配（正则需转义）。"""
    assert skill_hit("C++", {"c++", "ci/cd"}, "") is True
    assert skill_hit("CI/CD", set(), "负责 ci/cd 流水线") is True
    assert skill_hit("Node.js", {"node.js"}, "") is True
    # 不应被 C++ 误命中
    assert skill_hit("C++", {"c#"}, "只会 c#") is False


def test_chinese_skill_still_substring():
    """中文技能保留子串匹配：机器学习 命中 机器学习平台。"""
    assert skill_hit("机器学习", {"机器学习平台"}, "") is True
    assert skill_hit("机器学习", set(), "负责机器学习平台建设") is True


def test_hard_filter_excludes_frontend_for_java_role():
    cands = [
        _cand("frontend", ["JavaScript", "React"], "熟练掌握 JavaScript/TypeScript，前端工程师"),
        _cand("backend", ["Java"], "Java 后端开发五年"),
    ]
    passed = hard_filter(["精通 Java 开发"], ["Java"], cands)
    assert [c["candidate_id"] for c in passed] == ["backend"]


def test_hard_filter_skill_skips_when_jd_has_no_skill():
    """JD 硬性要求里没有技能词时，技能维度不参与过滤（不误杀）。

    注意：候选人学历缺失时会被学历门槛拦下（degree=0 < 2），所以这里给出本科学历，
    只考察「技能维度不生效」这一件事。
    """
    cands = [_cand("x", ["Go"], "写 Go 的", edu=[{"degree": "本科"}])]
    assert len(hard_filter(["本科及以上学历"], ["Go"], cands)) == 1


# ---------- 学历 / 年限 ----------
def test_required_and_candidate_degree():
    assert required_degree(["本科及以上学历"]) == 2
    assert required_degree(["硕士以上"]) == 3
    assert required_degree(["具备良好沟通能力"]) == 0
    assert candidate_degree({"education": [{"degree": "本科"}, {"degree": "硕士"}]}) == 3
    assert candidate_degree({}) == 0


def test_required_years_parsing():
    assert required_years(["3 年以上后端经验"]) == 3
    assert required_years(["经验丰富"]) == 0


def test_candidate_years_no_hardcoded_year():
    """在职经历按当前年份计算，不依赖硬编码年份。"""
    now = datetime.date.today().year
    years = candidate_years({"work_experience": [{"start_date": "2015.07", "end_date": ""}]})
    assert years == now - 2015
    # 多段不重叠经历求和
    total = candidate_years({
        "work_experience": [
            {"start_date": "2015.07", "end_date": "2018.06"},
            {"start_date": "2019.01", "end_date": "2021.01"},
        ]
    })
    assert total == 3 + 2


def test_hard_filter_degree_gate():
    cands = [
        _cand("college", ["Python"], "专科", edu=[{"degree": "专科"}]),
        _cand("bachelor", ["Python"], "本科", edu=[{"degree": "本科"}]),
    ]
    passed = hard_filter(["本科及以上学历", "精通 Python"], ["Python"], cands)
    assert [c["candidate_id"] for c in passed] == ["bachelor"]


def test_required_skills_extracts_tech_tokens():
    tags = required_skills(["精通 FastAPI / Flask 等框架", "3 年以上经验"])
    assert "FastAPI" in tags and "Flask" in tags
