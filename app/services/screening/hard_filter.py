from app.db.session import get_db
import json
import logging

logger = logging.getLogger(__name__)


def build_hard_filter(hard_requirements: list) -> tuple:
    """从硬性条件生成 MySQL 兼容的 JSON 过滤条件与参数。

    候选人 structured_json.education 结构为 [{"degree": "硕士", ...}, ...]。
    注意：PostgreSQL 的 JSONB 包含操作符 `@>` 在 MySQL 不可用，改用
    JSON_CONTAINS 并参数化候选值，避免字符串拼接注入。
    返回 (conditions, params)：conditions 为 SQL 片段列表，params 为对应参数。
    """
    conditions = []
    params = []
    for req in hard_requirements:
        req_lower = req.lower()
        # 学历硬性条件示例：匹配 education 数组中任一记录的 degree
        if "硕士" in req_lower or "研究生" in req_lower:
            conditions.append("JSON_CONTAINS(JSON_EXTRACT(structured_json, '$.education'), %s)")
            params.append('[{"degree": "硕士"}]')
        elif "本科" in req_lower:
            conditions.append("JSON_CONTAINS(JSON_EXTRACT(structured_json, '$.education'), %s)")
            params.append('[{"degree": "本科"}]')
        # 年限 / 地点 / 技能等硬性条件此处未实现（简化示例），后续可扩展
    return conditions, params


def get_filtered_candidate_ids(tenant_id: str, job_id: str, hard_requirements: list) -> list:
    conditions, params = build_hard_filter(hard_requirements)
    query = "SELECT id FROM candidates WHERE tenant_id = %s"
    query_params = [tenant_id]
    if conditions:
        query += " AND " + " AND ".join(conditions)
        query_params += params
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(query, query_params)
        return [row[0] for row in cur.fetchall()]