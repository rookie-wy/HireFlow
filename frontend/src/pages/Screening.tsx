import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Card,
  Form,
  Select,
  InputNumber,
  Input,
  Button,
  Space,
  Typography,
  Steps,
  Progress,
  Tag,
  Empty,
  Alert,
  Divider,
  Tooltip,
  Badge,
  Statistic,
  Row,
  Col,
  Timeline,
  Segmented,
} from 'antd'
import {
  PlayCircleOutlined,
  LikeOutlined,
  DislikeOutlined,
  ThunderboltOutlined,
  TeamOutlined,
  MessageOutlined,
  TrophyOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useLocation } from 'react-router-dom'
import { notifySuccess } from '../api/notify'
import { api, streamScreenEvents } from '../api/client'
import type {
  AgentDetail,
  Candidate,
  DiscussionTurn,
  FeedbackKind,
  Job,
  MatchResult,
  OverallReport,
  RoughCandidate,
  ScreenEvent,
  ScreeningTask,
} from '../api/types'

const DIM_LABEL: Record<string, string> = {
  skill: '技能匹配',
  experience: '经验匹配',
  culture: '文化契合',
  stability: '稳定性',
  leadership: '领导力',
  visual: '视觉设计',
  communication: '沟通表达',
  overall: '综合',
}

const AGENT_LABEL: Record<string, string> = {
  interviewer: '面试官',
  skill_evaluator: '技能评估',
  culture_fit: '文化契合',
  leadership: '领导力',
  visual_designer: '视觉设计',
  stability_analyzer: '稳定性分析(规则)',
}

const STANCE_META: Record<string, { color: string; text: string }> = {
  maintain: { color: 'default', text: '维持原判' },
  revise: { color: 'orange', text: '修正评分' },
  advocate: { color: 'red', text: '魔鬼代言人' },
  moderator: { color: 'blue', text: '主持人' },
}

const CONVERGENCE_TEXT: Record<string, string> = {
  consensus: '初始共识（无需讨论）',
  converged: '讨论后收敛',
  max_rounds: '达到最大轮次',
}

const STAGE_STEPS = ['混合粗筛', '专家独立评估', '分歧检测', '圆桌讨论', '仲裁与报告']

function scoreColor(score: number) {
  if (score >= 80) return '#52c41a'
  if (score >= 60) return '#1677ff'
  return '#fa8c16'
}

function dimLabel(k: string) {
  return DIM_LABEL[k] ?? k
}

function agentLabel(k: string) {
  return AGENT_LABEL[k] ?? k
}

interface CandidateLive {
  candidateId: string
  agents: string[]
  results: AgentDetail[]
  mean?: number
  std?: number
  needsDiscussion?: boolean
  turns: DiscussionTurn[]
  report?: OverallReport
  failed?: string
}

export default function Screening() {
  const location = useLocation() as { state?: { jobId?: string } }

  const [jobs, setJobs] = useState<Job[]>([])
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [form] = Form.useForm<{ job_id: string; max_candidates: number; query?: string }>()

  const [task, setTask] = useState<ScreeningTask | null>(null)
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [stageText, setStageText] = useState('')
  const [step, setStep] = useState(0)
  const [rough, setRough] = useState<RoughCandidate[]>([])
  const [poolSize, setPoolSize] = useState(0)
  const [live, setLive] = useState<Record<string, CandidateLive>>({})
  const [order, setOrder] = useState<string[]>([])
  const [results, setResults] = useState<MatchResult[]>([])
  const [boost, setBoost] = useState(0)
  const [cost, setCost] = useState({ tokens: 0, usd: 0 })
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState<Record<string, FeedbackKind>>({})
  const [selectedJobId, setSelectedJobId] = useState<string>('')
  /** 非空时结果区只展示本次任务的结果（避免与历史任务结果混排） */
  const [activeTaskId, setActiveTaskId] = useState<string>('')
  const [sortMode, setSortMode] = useState<'adjusted' | 'raw'>('adjusted')
  const [retrying, setRetrying] = useState(false)

  const cancelRef = useRef<(() => void) | null>(null)

  const jobTitle = useCallback(
    (id: string) => jobs.find((j) => j.id === id)?.title ?? id.slice(0, 8),
    [jobs],
  )
  const candName = useCallback(
    (id: string) => candidates.find((c) => c.id === id)?.name ?? id.slice(0, 8),
    [candidates],
  )

  useEffect(() => {
    void (async () => {
      try {
        const [js, cs] = await Promise.all([api.listJobs(), api.listCandidates()])
        setJobs(js)
        setCandidates(cs)
        if (location.state?.jobId) {
          form.setFieldValue('job_id', location.state.jobId)
          setSelectedJobId(location.state.jobId)
        }
      } catch {
        // 拦截器已提示
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => cancelRef.current?.(), [])

  const patchLive = useCallback((candidateId: string, patch: Partial<CandidateLive>) => {
    setLive((prev) => {
      const base: CandidateLive = prev[candidateId] ?? {
        candidateId,
        agents: [],
        results: [],
        turns: [],
      }
      return { ...prev, [candidateId]: { ...base, ...patch } }
    })
    setOrder((prev) => (prev.includes(candidateId) ? prev : [...prev, candidateId]))
  }, [])

  const loadResults = useCallback(
    async (jobId: string, taskId = '') => {
      try {
        const r = await api.matchResults(jobId)
        setResults(r.results)
        setBoost(r.boost)
        setActiveTaskId(taskId)
      } catch {
        // 拦截器已提示
      }
    },
    [],
  )

  /** 本地重算调分（反馈后无需等待下一次读接口） */
  const recompute = useCallback((items: MatchResult[], nextBoost: number) => {
    return items.map((m) => ({ ...m, adjusted_score: Number((m.overall_score * (1 + nextBoost)).toFixed(2)) }))
  }, [])

  const onEvent = useCallback(
    (ev: ScreenEvent) => {
      const p = ev.payload ?? {}
      if (typeof ev.progress === 'number') setProgress(ev.progress)

      switch (ev.type) {
        case 'stage':
          setStep(0)
          setStageText(p.stage === 'rough' ? '混合粗筛进行中…' : ev.message || '处理中…')
          break
        case 'rough_result': {
          setStep(1)
          setRough(p.candidates ?? [])
          setPoolSize(p.pool_size ?? 0)
          setStageText('专家独立评估进行中…')
          break
        }
        case 'fine_start':
          setStep(1)
          if (p.candidate_id) patchLive(p.candidate_id, { agents: p.agents ?? [] })
          break
        case 'agent_result':
          if (p.candidate_id && p.result) {
            setLive((prev) => {
              const base: CandidateLive = prev[p.candidate_id!] ?? {
                candidateId: p.candidate_id!,
                agents: [],
                results: [],
                turns: [],
              }
              return {
                ...prev,
                [p.candidate_id!]: { ...base, results: [...base.results, p.result as AgentDetail] },
              }
            })
            setOrder((prev) => (prev.includes(p.candidate_id!) ? prev : [...prev, p.candidate_id!]))
          }
          break
        case 'divergence':
          setStep(p.needs_discussion ? 3 : 2)
          if (p.candidate_id)
            patchLive(p.candidate_id, {
              mean: p.mean,
              std: p.std,
              needsDiscussion: p.needs_discussion,
            })
          break
        case 'discussion':
          if (p.candidate_id && p.turn) {
            const turn = p.turn
            setLive((prev) => {
              const base: CandidateLive = prev[p.candidate_id!] ?? {
                candidateId: p.candidate_id!,
                agents: [],
                results: [],
                turns: [],
              }
              return { ...prev, [p.candidate_id!]: { ...base, turns: [...base.turns, turn] } }
            })
          }
          break
        case 'candidate_done':
          setStep(4)
          if (p.candidate_id && p.report) patchLive(p.candidate_id, { report: p.report })
          break
        case 'candidate_failed':
          if (p.candidate_id) patchLive(p.candidate_id, { failed: ev.message || '精筛失败' })
          break
        case 'cost':
          if (p.usage) {
            setCost((prev) => ({
              tokens: prev.tokens + p.usage!.tokens_prompt + p.usage!.tokens_completion,
              usd: prev.usd + p.usage!.cost,
            }))
          }
          break
        case 'done':
          setProgress(100)
          setStep(5)
          setStageText('筛选完成')
          break
        case 'error':
          setError(ev.message || '筛选失败')
          setRunning(false)
          break
        default:
          break
      }
    },
    [patchLive],
  )

  const submit = async (v: { job_id: string; max_candidates: number; query?: string }) => {
    cancelRef.current?.()
    setRunning(true)
    setError('')
    setResults([])
    setActiveTaskId('')
    setLive({})
    setOrder([])
    setRough([])
    setCost({ tokens: 0, usd: 0 })
    setProgress(1)
    setStep(0)
    setStageText('任务已提交，等待 worker 调度…')
    setSelectedJobId(v.job_id)
    try {
      const sub = await api.submitScreen(v.job_id, v.max_candidates, v.query ?? '')
      setTask({
        id: sub.task_id,
        job_id: v.job_id,
        status: sub.status,
        progress: 1,
        candidates_n: v.max_candidates,
        error_msg: '',
      })
      let finished = false
      cancelRef.current = streamScreenEvents(
        sub.task_id,
        (ev) => {
          onEvent(ev)
          if (ev.type === 'done') {
            finished = true
            setRunning(false)
            void loadResults(v.job_id, sub.task_id)
          }
          if (ev.type === 'error') finished = true
        },
        (reason) => {
          if (!finished && reason === 'eof') {
            setRunning(false)
            void loadResults(v.job_id, sub.task_id)
          }
        },
      )
    } catch {
      setRunning(false)
      setProgress(0)
      setStageText('')
    }
  }

  /** 失败任务续跑：backend 会新建任务并复用已完成候选人的结论，这里订阅新任务事件流 */
  const retry = async () => {
    if (!task) return
    setRetrying(true)
    setError('')
    setLive({})
    setOrder([])
    setRough([])
    setProgress(1)
    setStep(0)
    setStageText('提交续跑任务…')
    try {
      const r = await api.retryScreen(task.id)
      setTask({
        id: r.task_id,
        job_id: task.job_id,
        status: r.status,
        progress: 1,
        candidates_n: task.candidates_n,
        error_msg: '',
      })
      notifySuccess(`续跑已受理，复用 ${r.reused_candidates} 位候选人的历史结论`)
      let finished = false
      cancelRef.current = streamScreenEvents(
        r.task_id,
        (ev) => {
          onEvent(ev)
          if (ev.type === 'done') {
            finished = true
            setRunning(false)
            void loadResults(task.job_id, r.task_id)
          }
          if (ev.type === 'error') finished = true
        },
        (reason) => {
          if (!finished && reason === 'eof') {
            setRunning(false)
            void loadResults(task.job_id, r.task_id)
          }
        },
      )
    } catch {
      // 拦截器已提示
    } finally {
      setRetrying(false)
    }
  }

  const onFeedback = async (r: MatchResult, kind: FeedbackKind) => {
    try {
      await api.submitFeedback(r.candidate_id, r.job_id, kind)
      const delta = kind === 'suitable' ? 0.05 : -0.05
      const nextBoost = Math.max(-0.15, Math.min(0.15, Number((boost + delta).toFixed(4))))
      setFeedback((prev) => ({ ...prev, [r.candidate_id]: kind }))
      setBoost(nextBoost)
      setResults((prev) => recompute(prev, nextBoost))
      notifySuccess(
        kind === 'suitable'
          ? `已标记合适，偏好权重 ${(nextBoost * 100).toFixed(0)}%（调分已更新）`
          : `已标记不合适，偏好权重 ${(nextBoost * 100).toFixed(0)}%（调分已更新）`,
      )
    } catch {
      // 拦截器已提示
    }
  }

  const sortedResults = useMemo(() => {
    const scoped = activeTaskId ? results.filter((r) => r.task_id === activeTaskId) : results
    const scoreOf = (m: MatchResult) =>
      sortMode === 'raw' ? m.overall_score : m.adjusted_score ?? m.overall_score
    return [...scoped].sort((a, b) => scoreOf(b) - scoreOf(a))
  }, [results, activeTaskId, sortMode])

  const liveList = useMemo(
    () => order.map((id) => live[id]).filter(Boolean),
    [order, live],
  )

  return (
    <Row gutter={16}>
      <Col xs={24} lg={8} xl={7}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card title="发起智能筛选">
            <Form
              form={form}
              layout="vertical"
              onFinish={submit}
              initialValues={{ max_candidates: 10 }}
            >
              <Form.Item name="job_id" label="岗位" rules={[{ required: true, message: '请选择岗位' }]}>
                <Select
                  placeholder="选择岗位"
                  showSearch
                  optionFilterProp="label"
                  onChange={setSelectedJobId}
                  options={jobs.map((j) => ({
                    value: j.id,
                    label: `${j.title}（${j.job_category}）`,
                  }))}
                  notFoundContent={<Empty description="请先在岗位管理创建岗位" />}
                />
              </Form.Item>
              <Form.Item
                name="max_candidates"
                label="粗筛入池人数（1-50）"
                rules={[{ required: true }]}
              >
                <InputNumber min={1} max={50} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="query" label="检索意图（可选，留空用 JD 全文）">
                <Input.TextArea rows={3} placeholder="例如：5 年以上 Python 后端 + 分布式经验" />
              </Form.Item>
              <Space>
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<PlayCircleOutlined />}
                  loading={running}
                  disabled={!jobs.length}
                >
                  {running ? '筛选进行中' : '开始筛选'}
                </Button>
                <Button
                  icon={<ThunderboltOutlined />}
                  disabled={!selectedJobId}
                  onClick={() => void loadResults(selectedJobId)}
                >
                  加载历史结果
                </Button>              </Space>
              {!candidates.length && (
                <Alert
                  style={{ marginTop: 12 }}
                  type="warning"
                  showIcon
                  message="候选人库为空，请先到「候选人」页上传简历"
                />
              )}
            </Form>
          </Card>

          <Card title="流程进度" size="small">
            <Steps
              direction="vertical"
              size="small"
              current={step}
              status={error ? 'error' : running ? 'process' : 'finish'}
              items={STAGE_STEPS.map((t) => ({ title: t }))}
            />
            {stageText && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {stageText}
              </Typography.Text>
            )}
            <Progress
              percent={progress}
              status={error ? 'exception' : running ? 'active' : 'normal'}
              style={{ marginTop: 8 }}
            />
            {cost.tokens > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                LLM 累计：{cost.tokens} tokens / ${cost.usd.toFixed(4)}
              </Typography.Text>
            )}
          </Card>

          {rough.length > 0 && (
            <Card title={`粗筛入池（${rough.length}/${poolSize}）`} size="small">
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                {rough.map((r) => (
                  <Row key={r.candidate_id} justify="space-between" align="middle">
                    <Col>
                      <Typography.Text>{candName(r.candidate_id)}</Typography.Text>
                    </Col>
                    <Col>
                      <Tag color={scoreColor(r.score)}>{r.score.toFixed(1)}</Tag>
                    </Col>
                  </Row>
                ))}
              </Space>
            </Card>
          )}
        </Space>
      </Col>

      <Col xs={24} lg={16} xl={17}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {error && (
            <Alert
              type="error"
              showIcon
              message="筛选失败"
              description={error}
              action={
                task ? (
                  <Button
                    size="small"
                    danger
                    icon={<ReloadOutlined />}
                    loading={retrying}
                    onClick={() => void retry()}
                  >
                    续跑（复用已完成）
                  </Button>
                ) : null
              }
            />
          )}

          <Card
            title={
              <Space>
                <TeamOutlined />
                <span>多 Agent 圆桌讨论实时视图</span>
                {task && <Tag color={running ? 'processing' : 'default'}>任务 {task.id.slice(0, 8)}</Tag>}
              </Space>
            }
            extra={
              running ? (
                <Badge status="processing" text="进行中" />
              ) : task ? (
                <Badge status={error ? 'error' : 'success'} text={error ? '失败' : '已完成'} />
              ) : null
            }
          >
            {!liveList.length && !running && (
              <Empty description="尚未发起筛选：选择岗位与入池人数后点击「开始筛选」，专家评估与讨论过程将实时呈现" />
            )}
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              {liveList.map((c) => (
                <LiveCandidateCard
                  key={c.candidateId}
                  data={c}
                  name={candName(c.candidateId)}
                  jobCategory={jobs.find((j) => j.id === selectedJobId)?.job_category ?? ''}
                />
              ))}
            </Space>
          </Card>

          {sortedResults.length > 0 && (
            <Card
              title={
                <Space>
                  <TrophyOutlined />
                  <span>筛选结果（{sortedResults.length}）</span>
                  <Tag color={activeTaskId ? 'blue' : 'default'}>
                    {activeTaskId ? `本次任务 ${activeTaskId.slice(0, 8)}` : '岗位历史全量'}
                  </Tag>
                  {boost !== 0 && (
                    <Tag color="gold">个性化偏好已生效 {(boost * 100).toFixed(0)}%</Tag>
                  )}
                </Space>
              }
              extra={
                <Segmented
                  size="small"
                  value={sortMode}
                  onChange={(v) => setSortMode(v as 'adjusted' | 'raw')}
                  options={[
                    { label: '按调分排序', value: 'adjusted' },
                    { label: '按原始分排序', value: 'raw' },
                  ]}
                />
              }
            >
              <Row gutter={[16, 16]}>
                {sortedResults.map((r, idx) => (
                  <Col xs={24} xl={12} key={r.id}>
                    <ResultCard
                      rank={idx + 1}
                      result={r}
                      name={candName(r.candidate_id)}
                      feedback={feedback[r.candidate_id]}
                      onFeedback={onFeedback}
                    />
                  </Col>
                ))}
              </Row>
            </Card>
          )}

          {selectedJobId && sortedResults.length === 0 && !running && (
            <Card>
              <Empty description={`岗位「${jobTitle(selectedJobId)}」暂无匹配结果，可点击「加载历史结果」或发起新筛选`} />
            </Card>
          )}
        </Space>
      </Col>
    </Row>
  )
}

/** 单候选人实时过程：专家评估 → 分歧 → 讨论时间线 → 仲裁报告 */
function LiveCandidateCard({
  data,
  name,
}: {
  data: CandidateLive
  name: string
  jobCategory: string
}) {
  const [tab, setTab] = useState<'agents' | 'discussion'>('agents')
  const report = data.report
  const score = report?.overall_score
  const sortedAgents = useMemo(
    () => [...data.results].sort((a, b) => b.score - a.score),
    [data.results],
  )

  return (
    <Card
      size="small"
      style={{ borderLeft: `4px solid ${score != null ? scoreColor(score) : '#d9d9d9'}` }}
      title={
        <Space wrap>
          <Typography.Text strong>{name}</Typography.Text>
          {data.failed && <Tag color="red">精筛失败</Tag>}
          {score != null && <Tag color={scoreColor(score)}>综合 {score.toFixed(1)}</Tag>}
          {data.mean != null && (
            <Tooltip title="初始专家评分均值 / 标准差（标准差 > 12 触发圆桌讨论）">
              <Tag color={data.needsDiscussion ? 'volcano' : 'green'}>
                均值 {data.mean} · σ {data.std}
                {data.needsDiscussion ? ' · 触发讨论' : ' · 无需讨论'}
              </Tag>
            </Tooltip>
          )}
          {report?.discussion?.meta && (
            <Tag color="geekblue">
              {CONVERGENCE_TEXT[report.discussion.meta.convergence] ?? report.discussion.meta.convergence}
              {report.discussion.meta.devil_advocate_used ? ' · 含魔鬼代言人' : ''}
            </Tag>
          )}
        </Space>
      }
      extra={
        <Segmented
          size="small"
          value={tab}
          onChange={(v) => setTab(v as 'agents' | 'discussion')}
          options={[
            { label: `专家评估 ${data.results.length}`, value: 'agents' },
            { label: `讨论回放 ${data.turns.length}`, value: 'discussion' },
          ]}
        />
      }
    >
      {data.failed && <Alert type="error" showIcon message={data.failed} style={{ marginBottom: 8 }} />}

      {tab === 'agents' && (
        <Row gutter={[8, 8]}>
          {sortedAgents.map((a) => (
            <Col xs={24} md={12} key={a.agent}>
              <Card size="small" type="inner" title={
                <Space size={4}>
                  <span>{agentLabel(a.agent)}</span>
                  <Tag color={scoreColor(a.score)}>{a.score.toFixed(0)}</Tag>
                  {a.stance && (
                    <Tag color={STANCE_META[a.stance]?.color}>{STANCE_META[a.stance]?.text ?? a.stance}</Tag>
                  )}
                </Space>
              }>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {Object.entries(a.dimension_scores ?? {}).map(([k, v]) => (
                    <div key={k}>
                      <Typography.Text style={{ fontSize: 12 }}>
                        {dimLabel(k)} {v}
                      </Typography.Text>
                      <Progress percent={v} showInfo={false} size="small" strokeColor={scoreColor(v)} />
                    </div>
                  ))}
                  {a.reasoning && (
                    <Typography.Paragraph
                      type="secondary"
                      style={{ fontSize: 12, marginBottom: 4 }}
                      ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                    >
                      {a.reasoning}
                    </Typography.Paragraph>
                  )}
                  {a.evidence?.slice(0, 3).map((e, i) => (
                    <Typography.Text key={i} style={{ fontSize: 12 }}>
                      · {e}
                    </Typography.Text>
                  ))}
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    置信度 {(a.confidence * 100).toFixed(0)}%
                  </Typography.Text>
                </Space>
              </Card>
            </Col>
          ))}
          {!sortedAgents.length && <Col span={24}><Empty description="等待专家评估…" /></Col>}
        </Row>
      )}

      {tab === 'discussion' && (
        <>
          {data.turns.length === 0 && (
            <Empty description={data.needsDiscussion === false ? '专家评分一致，未触发圆桌讨论' : '等待讨论…'} />
          )}
          {data.turns.length > 0 && (
            <Timeline
              items={data.turns.map((t, i) => ({
                key: `${t.round}-${t.agent}-${i}`,
                color: t.stance === 'revise' ? 'orange' : t.stance === 'advocate' ? 'red' : 'blue',
                children: (
                  <Space direction="vertical" size={2} style={{ width: '100%' }}>
                    <Space size={4} wrap>
                      <Tag color="blue">第 {t.round} 轮</Tag>
                      <Typography.Text strong>{agentLabel(t.agent)}</Typography.Text>
                      <Tag color={STANCE_META[t.stance]?.color}>{STANCE_META[t.stance]?.text ?? t.stance}</Tag>
                      {t.score != null && <Tag color={scoreColor(t.score)}>{t.score.toFixed(0)}</Tag>}
                      {t.score_delta != null && t.score_delta !== 0 && (
                        <Tag color={t.score_delta > 0 ? 'green' : 'red'}>
                          {t.score_delta > 0 ? '+' : ''}
                          {t.score_delta.toFixed(1)}
                        </Tag>
                      )}
                    </Space>
                    <Typography.Text style={{ fontSize: 13 }}>{t.content}</Typography.Text>
                  </Space>
                ),
              }))}
            />
          )}
        </>
      )}

      {report && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Row gutter={16} align="middle">
            <Col flex="160px">
              <Statistic
                title="仲裁综合分"
                value={report.overall_score}
                precision={1}
                valueStyle={{ color: scoreColor(report.overall_score), fontSize: 26 }}
              />
            </Col>
            <Col flex="auto">
              {Object.entries(report.dimension_scores ?? {}).map(([k, v]) => (
                <div key={k}>
                  <Typography.Text style={{ fontSize: 12 }}>
                    {dimLabel(k)} {v}
                  </Typography.Text>
                  <Progress percent={v} showInfo={false} size="small" strokeColor={scoreColor(v)} />
                </div>
              ))}
            </Col>
          </Row>
          <Alert
            style={{ marginTop: 8 }}
            type="success"
            showIcon
            message={report.recommendation_text || '（无推荐语）'}
          />
          {report.evidence?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                关键证据：
              </Typography.Text>
              {report.evidence.map((e, i) => (
                <div key={i}>
                  <Typography.Text style={{ fontSize: 12 }}>· {e}</Typography.Text>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  )
}

/** 落库结果卡片：调分、维度、推荐语、讨论回放、反馈 */
function ResultCard({
  rank,
  result,
  name,
  feedback,
  onFeedback,
}: {
  rank: number
  result: MatchResult
  name: string
  feedback?: FeedbackKind
  onFeedback: (r: MatchResult, kind: FeedbackKind) => void
}) {
  const [open, setOpen] = useState(false)
  const adjusted = result.adjusted_score ?? result.overall_score
  const turns = result.discussion_json?.turns ?? []
  const agents = result.discussion_json?.agent_details ?? []

  return (
    <Card
      size="small"
      style={{ height: '100%', borderLeft: `4px solid ${scoreColor(adjusted)}` }}
      title={
        <Space wrap>
          <Tag color={rank <= 3 ? 'gold' : 'default'}>#{rank}</Tag>
          <Typography.Text strong>{name}</Typography.Text>
          <Tag color={scoreColor(adjusted)}>{adjusted.toFixed(1)} 分</Tag>
          {result.adjusted_score != null && result.adjusted_score !== result.overall_score && (
            <Tooltip
              title={`原始分 ${result.overall_score.toFixed(2)} × (1 + 偏好) = ${result.adjusted_score.toFixed(2)}`}
            >
              <Tag color="gold">调分自 {result.overall_score.toFixed(1)}</Tag>
            </Tooltip>
          )}
        </Space>
      }
      actions={[
        <Tooltip title="合适：偏好 +0.05，后续筛选读时提权" key="up">
          <Button
            type={feedback === 'suitable' ? 'primary' : 'text'}
            size="small"
            icon={<LikeOutlined />}
            onClick={() => onFeedback(result, 'suitable')}
          >
            合适
          </Button>
        </Tooltip>,
        <Tooltip title="不合适：偏好 -0.05" key="down">
          <Button
            type={feedback === 'not_suitable' ? 'primary' : 'text'}
            danger={feedback === 'not_suitable'}
            size="small"
            icon={<DislikeOutlined />}
            onClick={() => onFeedback(result, 'not_suitable')}
          >
            不合适
          </Button>
        </Tooltip>,
        <Button key="detail" type="text" size="small" icon={<MessageOutlined />} onClick={() => setOpen(!open)}>
          {open ? '收起' : '讨论回放'}
        </Button>,
      ]}
    >
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        {Object.entries(result.dimension_scores ?? {}).map(([k, v]) => (
          <div key={k}>
            <Typography.Text style={{ fontSize: 12 }}>
              {dimLabel(k)} {v}
            </Typography.Text>
            <Progress percent={v} showInfo={false} size="small" strokeColor={scoreColor(v)} />
          </div>
        ))}
        <Typography.Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
          {result.recommendation_text}
        </Typography.Paragraph>
        {result.evidence?.slice(0, 3).map((e, i) => (
          <Typography.Text key={i} type="secondary" style={{ fontSize: 12 }}>
            · {e}
          </Typography.Text>
        ))}

        {open && (
          <>
            <Divider style={{ margin: '8px 0' }} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              专家评估（{agents.length}）
            </Typography.Text>
            <Space size={[4, 4]} wrap>
              {agents.map((a) => (
                <Tooltip key={a.agent} title={(a.evidence ?? []).join('\n')}>
                  <Tag color={scoreColor(a.score)}>
                    {agentLabel(a.agent)} {a.score.toFixed(0)}
                  </Tag>
                </Tooltip>
              ))}
            </Space>
            {turns.length > 0 && (
              <>
                <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
                  讨论记录（{turns.length} 条发言）
                </Typography.Text>
                <Timeline
                  items={turns.map((t, i) => ({
                    key: i,
                    color: t.stance === 'revise' ? 'orange' : 'blue',
                    children: (
                      <div>
                        <Space size={4} wrap>
                          <Tag>第 {t.round} 轮</Tag>
                          <Typography.Text strong style={{ fontSize: 12 }}>
                            {agentLabel(t.agent)}
                          </Typography.Text>
                          <Tag color={STANCE_META[t.stance]?.color}>{STANCE_META[t.stance]?.text ?? t.stance}</Tag>
                        </Space>
                        <Typography.Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
                          {t.content}
                        </Typography.Paragraph>
                      </div>
                    ),
                  }))}
                />
              </>
            )}
          </>
        )}
      </Space>
    </Card>
  )
}
