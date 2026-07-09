from app.db.session import get_db
import json
import logging

logger = logging.getLogger(__name__)


def build_hard_filter_query(hard_requirements: list) -> str:
    """从硬性条件列表生成JSONB查询条件，此处为简化示例"""
    conditions = []
    for req in hard_requirements:
        req_lower = req.lower()
        # 学历示例
        if "硕士" in req_lower or "研究生" in req_lower:
            conditions.append("structured_json->'education' @> '[{\"degree\": \"硕士\"}]'")
        elif "本科" in req_lower:
            conditions.append("structured_json->'education' @> '[{\"degree\": \"本科\"}]'")
        # 年限示例（需从描述中提取数字）
        # 此处简化，生产环境中需更健壮的解析
        # 地点、技能等类似处理
    if not conditions:
        return ""
    return " AND " + " AND ".join(conditions)


def get_filtered_candidate_ids(tenant_id: str, job_id: str, hard_requirements: list) -> list:
    if not hard_requirements:
        # 无硬性条件则返回所有候选人ID
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM candidates WHERE tenant_id = %s", (tenant_id,))
            return [row[0] for row in cur.fetchall()]

    filter_sql = build_hard_filter_query(hard_requirements)
    query = f"SELECT id FROM candidates WHERE tenant_id = %s {filter_sql}"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(query, (tenant_id,))
        return [row[0] for row in cur.fetchall()]