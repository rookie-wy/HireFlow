-- 0003: 岗位级配置（O7）
-- weights_override：岗位级仲裁权重覆盖（JSON，键为专家名、值为权重，和应为 1）
-- screen_overrides：岗位级检索/重排参数覆盖（JSON，如 rag_top_k / rerank_threshold / rerank_mode / chunk_size）
-- 均为可空列：为空时沿用「岗位类别默认权重 + 全局检索参数」，既有行为不变。
ALTER TABLE jobs
    ADD COLUMN weights_override JSON NULL,
    ADD COLUMN screen_overrides JSON NULL;
