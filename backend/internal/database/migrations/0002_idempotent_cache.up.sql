-- 0002: 幂等缓存支持
-- 1) candidates.profile_hash：简历内容指纹（原文 + 结构化字段），重筛时用于判断能否复用精筛结论
-- 2) match_results.profile_hash：该行结果对应的指纹
-- 3) 清理历史重复行（同租户+岗位+候选人保留最新一行）
-- 4) 唯一键 uk_job_candidate：同岗位同候选人只保留一行，重筛改为覆盖更新（避免结果表堆垃圾行）

ALTER TABLE candidates
    ADD COLUMN profile_hash VARCHAR(64) NOT NULL DEFAULT '',
    ADD INDEX idx_candidates_profile_hash (profile_hash);

ALTER TABLE match_results
    ADD COLUMN profile_hash VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;

-- 去重：保留每个 (tenant_id, job_id, candidate_id) 中 created_at 最新的一行
DELETE older FROM match_results older
JOIN match_results newer
  ON older.tenant_id = newer.tenant_id
 AND older.job_id = newer.job_id
 AND older.candidate_id = newer.candidate_id
 AND (older.created_at < newer.created_at
      OR (older.created_at = newer.created_at AND older.id < newer.id));

-- 加唯一键（去重后不会冲突）
ALTER TABLE match_results
    ADD UNIQUE KEY uk_job_candidate (tenant_id, job_id, candidate_id);
