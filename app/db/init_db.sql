-- 数据库初始化脚本（幂等，可重复执行；init_pool 启动时自动执行）

CREATE TABLE IF NOT EXISTS users (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(32) NOT NULL,
    username VARCHAR(100),
    password_hash VARCHAR(255),
    role VARCHAR(20) NOT NULL CHECK (role IN ('hr','manager','admin')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_users_username_tenant (tenant_id, username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jobs (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(32) NOT NULL,
    title VARCHAR(255),
    jd_text TEXT,
    jd_json JSON,
    job_category VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_jobs_tenant_id (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS candidates (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(32) NOT NULL,
    name VARCHAR(100),
    email VARCHAR(255),
    phone VARCHAR(50),
    resume_text TEXT,
    structured_json JSON,
    embedding_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_candidates_tenant_id (tenant_id),
    UNIQUE INDEX idx_candidates_email_tenant (tenant_id, email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS match_results (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(32) NOT NULL,
    job_id CHAR(36) NOT NULL,
    candidate_id CHAR(36) NOT NULL,
    overall_score FLOAT,
    dimension_scores JSON,
    recommendation_text TEXT,
    evidence JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id),
    FOREIGN KEY (candidate_id) REFERENCES candidates(id),
    INDEX idx_match_tenant_job (tenant_id, job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS interaction_log (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(32) NOT NULL,
    session_id VARCHAR(64),
    user_id VARCHAR(32),
    event_type VARCHAR(20),
    target_id CHAR(36),
    feedback VARCHAR(20),
    summary_vector_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_interaction_session (tenant_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cost_records (
    id CHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(32) NOT NULL,
    trace_id VARCHAR(64),
    model_name VARCHAR(50),
    tokens_prompt INT,
    tokens_completion INT,
    cost FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_cost_tenant_date (tenant_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
