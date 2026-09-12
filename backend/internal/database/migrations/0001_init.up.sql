-- 0001 初始schema：v4 六表（兼容旧数据）+ v5 新增 screening_tasks
CREATE TABLE IF NOT EXISTS users (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'hr',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant_username (tenant_id, username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jobs (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    title VARCHAR(256) NOT NULL DEFAULT '',
    jd_text TEXT,
    jd_json JSON,
    job_category VARCHAR(32) NOT NULL DEFAULT 'general',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS candidates (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL DEFAULT '',
    email VARCHAR(256) NOT NULL,
    phone VARCHAR(32) NOT NULL DEFAULT '',
    resume_text MEDIUMTEXT,
    structured_json JSON,
    embedding_id VARCHAR(128) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    UNIQUE KEY uk_tenant_email (tenant_id, email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS match_results (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    job_id CHAR(36) NOT NULL,
    candidate_id CHAR(36) NOT NULL,
    task_id CHAR(36) NOT NULL DEFAULT '',
    overall_score DECIMAL(6,2) NOT NULL DEFAULT 0,
    dimension_scores JSON,
    recommendation_text TEXT,
    evidence JSON,
    discussion_json JSON,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant_job (tenant_id, job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS interaction_log (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL DEFAULT '',
    user_id CHAR(36) NOT NULL DEFAULT '',
    event_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(128) NOT NULL DEFAULT '',
    job_id CHAR(36) NOT NULL DEFAULT '',
    feedback VARCHAR(32) NOT NULL DEFAULT '',
    summary_vector_id VARCHAR(128) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant_session (tenant_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cost_records (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    tokens_prompt INT NOT NULL DEFAULT 0,
    tokens_completion INT NOT NULL DEFAULT 0,
    cost DECIMAL(12,6) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant_created (tenant_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS screening_tasks (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    job_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL DEFAULT '',
    session_id VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    progress INT NOT NULL DEFAULT 0,
    candidates_n INT NOT NULL DEFAULT 0,
    error_msg VARCHAR(512) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tenant_job (tenant_id, job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
