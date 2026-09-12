import axios from 'axios'
import type {
  ApiResponse,
  Candidate,
  CreateJobResult,
  FeedbackKind,
  InterviewDraft,
  InterviewSendResult,
  Job,
  LoginResult,
  MatchResultsResult,
  MeResult,
  ReplyIntent,
  RetryScreenResult,
  ScreenEvent,
  SubmitScreenResult,
  TaskStatusResult,
  UploadResult,
} from './types'
import { notifyError } from './notify'
import { useAuthStore } from '../stores/auth'

export const http = axios.create({ baseURL: '/api/v1', timeout: 300000 })

http.interceptors.request.use((cfg) => {
  const token = useAuthStore.getState().token
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

http.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse<unknown>
    if (body && typeof body.code === 'number' && body.code >= 400) {
      notifyError(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    return resp
  },
  (err) => {
    if (err.response?.status === 401) {
      useAuthStore.getState().logout()
      notifyError('登录已过期，请重新登录')
      window.location.hash = '#/login'
    } else {
      notifyError(err.response?.data?.message || err.message || '网络错误')
    }
    return Promise.reject(err)
  },
)

/** 统一拆包：{code,message,data} → data */
async function unwrap<T>(p: Promise<{ data: ApiResponse<T> }>): Promise<T> {
  const resp = await p
  return resp.data.data as T
}

// ---- 认证 ----
export const api = {
  login: (username: string, password: string, tenant_id: string) =>
    unwrap<LoginResult>(http.post('/auth/login', { username, password, tenant_id })),

  register: (username: string, password: string, tenant_id: string, role = 'hr') =>
    unwrap<LoginResult>(http.post('/auth/register', { username, password, tenant_id, role })),

  me: () => unwrap<MeResult>(http.get('/auth/me')),

  // ---- 岗位 ----
  createJob: (jd_text: string, language = 'zh') =>
    unwrap<CreateJobResult>(http.post('/jobs', { jd_text, language })),

  listJobs: () => unwrap<Job[]>(http.get('/jobs')),

  deleteJob: (jobId: string) => unwrap<null>(http.delete(`/jobs/${jobId}`)),

  /** 设置岗位级配置（权重 / 检索参数覆盖），仅 manager+ 可调用 */
  updateJobOverrides: (jobId: string, weights: Record<string, number>, screen: Record<string, number | string>) =>
    unwrap<Job>(http.put(`/jobs/${jobId}/overrides`, { weights, screen })),

  // ---- 候选人 ----
  uploadCandidate: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return unwrap<UploadResult>(
      http.post('/candidates/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    )
  },

  listCandidates: () => unwrap<Candidate[]>(http.get('/candidates')),

  deleteCandidate: (candidateId: string) =>
    unwrap<null>(http.delete(`/candidates/${candidateId}`)),

  // ---- 筛选 ----
  submitScreen: (job_id: string, max_candidates: number, query = '') =>
    unwrap<SubmitScreenResult>(http.post('/screen', { job_id, max_candidates, query })),

  taskStatus: (taskId: string) => unwrap<TaskStatusResult>(http.get(`/screen/tasks/${taskId}`)),

  /** 失败任务续跑：复用已完成候选人结论，只补未完成部分 */
  retryScreen: (taskId: string) =>
    unwrap<RetryScreenResult>(http.post(`/screen/tasks/${taskId}/retry`)),

  matchResults: (jobId: string) =>
    unwrap<MatchResultsResult>(http.get('/screen/match-results', { params: { job_id: jobId } })),

  submitFeedback: (candidate_id: string, job_id: string, feedback: FeedbackKind) =>
    unwrap<{ status: string }>(http.post('/feedback', { candidate_id, job_id, feedback })),

  // ---- 面试 ----
  interviewDraft: (job_id: string, candidate_id: string, proposed_times: string[]) =>
    unwrap<InterviewDraft>(http.post('/interview/draft', { job_id, candidate_id, proposed_times })),

  interviewSend: (
    job_id: string,
    candidate_id: string,
    draft: InterviewDraft,
    selected_time: string,
  ) =>
    unwrap<InterviewSendResult>(
      http.post('/interview/send', { job_id, candidate_id, draft, selected_time }),
    ),

  interviewReplyIntent: (reply_body: string) =>
    unwrap<ReplyIntent>(http.post('/interview/reply-intent', { reply_body })),
}

/** 归一化事件：backend 把 agent 原始字段统一放进 payload 层（同时平铺一层便于直取）。 */
export function normalizeEvent(raw: Record<string, unknown>): ScreenEvent {
  const payload = (raw.payload ?? {}) as Record<string, unknown>
  return { ...payload, ...raw, payload } as ScreenEvent
}

/**
 * SSE 事件流（EventSource 无法携带 Authorization，故用 fetch 流式读取）。
 * 返回取消函数。
 */
export function streamScreenEvents(
  taskId: string,
  onEvent: (event: ScreenEvent) => void,
  onClose?: (reason: 'eof' | 'aborted' | 'error') => void,
): () => void {
  const controller = new AbortController()
  const token = useAuthStore.getState().token

  const run = async () => {
    try {
      const resp = await fetch(`/api/v1/screen/tasks/${taskId}/events`, {
        headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
        signal: controller.signal,
      })
      if (!resp.ok || !resp.body) {
        notifyError(`事件流连接失败 (${resp.status})`)
        onClose?.('error')
        return
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() ?? ''
        for (const block of blocks) {
          for (const line of block.split('\n')) {
            const trimmed = line.trim()
            if (!trimmed.startsWith('data:')) continue
            const body = trimmed.slice(5).trim()
            if (!body) continue
            try {
              onEvent(normalizeEvent(JSON.parse(body) as Record<string, unknown>))
            } catch {
              // 忽略无法解析的行，保证流不中断
            }
          }
        }
      }
      onClose?.('eof')
    } catch (e) {
      if ((e as Error).name === 'AbortError') onClose?.('aborted')
      else onClose?.('error')
    }
  }

  void run()
  return () => controller.abort()
}
