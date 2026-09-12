// 统一 API 类型（与 backend internal/agenttypes + agent Pydantic 模型逐字段对齐）
export interface ApiResponse<T> {
  code: number
  message: string
  data?: T
  trace_id?: string
}

export type Role = 'hr' | 'manager' | 'admin'

export interface LoginResult {
  access_token: string
  token_type: string
  user_id: string
  tenant_id: string
  role: Role
}

export interface MeResult {
  user_id: string
  tenant_id: string
  role: Role
}

export interface JobDescription {
  title: string
  hard_requirements: string[]
  soft_requirements: string[]
  skill_graph: string[]
  job_category: string
}

export interface Job {
  id: string
  tenant_id: string
  title: string
  jd_text: string
  jd_json?: Partial<JobDescription>
  job_category: string
  /** 岗位级权重覆盖（专家名 → 权重），为空表示用类别默认 */
  weights_override?: Record<string, number>
  /** 岗位级检索/重排参数覆盖 */
  screen_overrides?: Record<string, number | string>
  created_at: string
}

/** 岗位级配置（O7） */
export interface JobOverrides {
  weights: Record<string, number>
  screen: Record<string, number | string>
}

export interface CreateJobResult {
  job: Job
  parsed: JobDescription
}

export interface WorkExperience {
  company: string
  title: string
  start_date: string
  end_date?: string
  description?: string
}

export interface Education {
  school: string
  degree: string
  major?: string
  start_date?: string
  end_date?: string
}

export interface CandidateProfile {
  name: string
  email: string
  phone: string
  work_experience: WorkExperience[]
  education: Education[]
  skills: string[]
  raw_text?: string
  vector_chunks?: number
  usage?: CostUsage
}

export interface Candidate {
  id: string
  tenant_id: string
  name: string
  email: string
  phone: string
  resume_text?: string
  structured_json?: {
    work_experience?: WorkExperience[]
    education?: Education[]
    skills?: string[]
  }
  embedding_id?: string
  created_at: string
}

export interface UploadResult {
  candidate_id: string
  profile: CandidateProfile
}

// ---- 筛选：精筛报告 ----
export interface AgentDetail {
  agent: string
  score: number
  dimension_scores: Record<string, number>
  evidence: string[]
  confidence: number
  stance?: 'maintain' | 'revise' | null
  reasoning?: string
  round?: number
}

export interface DiscussionTurn {
  round: number
  agent: string
  stance: 'maintain' | 'revise' | 'advocate' | 'moderator'
  content: string
  score?: number | null
  score_delta?: number | null
}

export interface DiscussionMeta {
  rounds: number
  convergence: 'consensus' | 'converged' | 'max_rounds'
  devil_advocate_used: boolean
  initial_mean: number
  initial_std: number
  final_mean: number
  final_std: number
  initial_scores: Record<string, number>
  final_scores: Record<string, number>
}

export interface DiscussionTranscript {
  turns: DiscussionTurn[]
  meta: DiscussionMeta
}

/** 后端把 discussion + agent_details 一起塞进 match_results.discussion_json */
export interface DiscussionJSON extends Partial<DiscussionTranscript> {
  agent_details?: AgentDetail[]
}

export interface MatchResult {
  id: string
  tenant_id?: string
  job_id: string
  candidate_id: string
  task_id: string
  overall_score: number
  adjusted_score?: number
  dimension_scores: Record<string, number>
  recommendation_text: string
  evidence: string[]
  discussion_json?: DiscussionJSON
  created_at: string
}

// ---- 筛选：任务与事件 ----
/** 失败任务续跑结果（O5） */
export interface RetryScreenResult {
  task_id: string
  status: ScreeningTask['status']
  session_id: string
  parent_task_id: string
  reused_candidates: number
}

export interface ScreeningTask {
  id: string
  tenant_id?: string
  job_id: string
  user_id?: string
  session_id?: string
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  progress: number
  candidates_n: number
  error_msg: string
  created_at?: string
  updated_at?: string
}

export interface SubmitScreenResult {
  task_id: string
  status: ScreeningTask['status']
  session_id: string
}

export interface RoughCandidate {
  candidate_id: string
  score: number
  reasons?: string[]
  evidence?: string[]
  [k: string]: unknown
}

export interface TaskStatusResult {
  task: ScreeningTask
  boost: number
  results: MatchResult[]
}

export interface MatchResultsResult {
  boost: number
  results: MatchResult[]
}

/** 精筛报告（candidate_done / done 事件载荷，agent OverallReport） */
export interface OverallReport {
  candidate_id: string
  overall_score: number
  dimension_scores: Record<string, number>
  recommendation_text: string
  evidence: string[]
  agent_details: AgentDetail[]
  discussion?: DiscussionTranscript | null
}

export interface CostUsage {
  model_name: string
  tokens_prompt: number
  tokens_completion: number
  cost: number
}

export type ScreenEventType =
  | 'stage'
  | 'rough_result'
  | 'fine_start'
  | 'agent_result'
  | 'divergence'
  | 'discussion'
  | 'candidate_done'
  | 'candidate_failed'
  | 'fine_done'
  | 'cost'
  | 'done'
  | 'error'

/**
 * SSE 事件（backend ScreeningEvent 包一层：agent 原始载荷统一放 payload）。
 * agent 原始字段：stage / rough_result / fine_start / agent_result /
 * divergence / discussion / candidate_done / candidate_failed / cost / done / error
 */
export interface ScreenEvent {
  type: ScreenEventType
  task_id: string
  progress?: number
  message?: string
  payload?: {
    // stage
    stage?: string
    // rough_result
    candidates?: RoughCandidate[]
    pool_size?: number
    // fine_start
    candidate_id?: string
    agents?: string[]
    // agent_result
    result?: AgentDetail
    // divergence
    mean?: number
    std?: number
    needs_discussion?: boolean
    // discussion
    turn?: DiscussionTurn
    // candidate_done / done
    report?: OverallReport
    results?: OverallReport[]
    // cost
    usage?: CostUsage
    // error
    code?: number
  }
  /** payload 直通后的原始字段（防御式兼容：agent 字段被平铺时仍可读） */
  [k: string]: unknown
  occurred_at?: number
}

// ---- 反馈 ----
export type FeedbackKind = 'suitable' | 'not_suitable'

// ---- 面试调度 ----
export interface InterviewDraft {
  candidate_email: string
  subject: string
  body: string
  proposed_times: string[]
}

export interface InterviewSendResult {
  status: string
  email_id?: string
  calendar_event_id?: string
  [k: string]: string | undefined
}

export interface ReplyIntent {
  intent: 'accept' | 'propose_new_time' | 'decline' | 'other'
  new_times?: string[]
  message?: string
}
