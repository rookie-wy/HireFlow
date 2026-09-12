-- 0004: 幂等缓存加入"岗位配置指纹"（O7 修复）
-- 问题：缓存只按简历指纹（candidate profile_hash）命中，改了岗位权重/检索参数后重筛仍复用旧结论，
--       表现为"配置改了但分数不变"。
-- 方案：match_results 记录当时生效的岗位配置指纹，缓存命中需同时满足 简历指纹 + 配置指纹 一致。
ALTER TABLE match_results
    ADD COLUMN config_hash VARCHAR(64) NOT NULL DEFAULT '',
    ADD INDEX idx_match_config_hash (config_hash);
