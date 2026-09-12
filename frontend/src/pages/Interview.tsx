import { useCallback, useEffect, useState } from 'react'
import {
  Card,
  Form,
  Select,
  Input,
  Button,
  Space,
  Typography,
  Tag,
  Radio,
  Alert,
  Empty,
  Row,
  Col,
  Descriptions,
  Divider,
  Steps,
} from 'antd'
import { SendOutlined, FileTextOutlined, RobotOutlined } from '@ant-design/icons'
import { notifySuccess, notifyWarning } from '../api/notify'
import { api } from '../api/client'
import type { Candidate, InterviewDraft, Job, ReplyIntent } from '../api/types'

const INTENT_META: Record<string, { color: string; text: string }> = {
  accept: { color: 'green', text: '接受面试邀请' },
  propose_new_time: { color: 'orange', text: '提议新时间' },
  decline: { color: 'red', text: '婉拒' },
  other: { color: 'default', text: '其他/需人工确认' },
}

export default function Interview() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [form] = Form.useForm<{ job_id: string; candidate_id: string; times: string }>()

  const [draft, setDraft] = useState<InterviewDraft | null>(null)
  const [selectedTime, setSelectedTime] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [sending, setSending] = useState(false)
  const [sendResult, setSendResult] = useState<Record<string, string> | null>(null)
  const [replyBody, setReplyBody] = useState('')
  const [intent, setIntent] = useState<ReplyIntent | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [step, setStep] = useState(0)

  useEffect(() => {
    void (async () => {
      try {
        const [js, cs] = await Promise.all([api.listJobs(), api.listCandidates()])
        setJobs(js)
        setCandidates(cs)
      } catch {
        // 拦截器已提示
      }
    })()
  }, [])

  const candidateEmail = useCallback(
    (id: string) => candidates.find((c) => c.id === id)?.email ?? '',
    [candidates],
  )
  const candidateName = useCallback(
    (id: string) => candidates.find((c) => c.id === id)?.name ?? '',
    [candidates],
  )

  const parseTimes = (raw: string) =>
    raw
      .split(/[\n,，;；]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 10)

  const onDraft = async (v: { job_id: string; candidate_id: string; times: string }) => {
    const times = parseTimes(v.times)
    if (!times.length) {
      notifyWarning('请至少提供一个候选时间段')
      return
    }
    setDrafting(true)
    setSendResult(null)
    try {
      const d = await api.interviewDraft(v.job_id, v.candidate_id, times)
      setDraft(d)
      setSelectedTime(d.proposed_times?.[0] ?? times[0])
      setStep(1)
      notifySuccess('草稿生成成功，请确认后发送')
    } catch {
      // 拦截器已提示
    } finally {
      setDrafting(false)
    }
  }

  const onSend = async () => {
    if (!draft) return
    const v = form.getFieldsValue()
    setSending(true)
    try {
      const r = await api.interviewSend(v.job_id, v.candidate_id, draft, selectedTime)
      setSendResult(r as Record<string, string>)
      setStep(2)
      notifySuccess('面试邀请已发送（邮件必达，日历尽力而为）')
    } catch {
      // 拦截器已提示
    } finally {
      setSending(false)
    }
  }

  const onAnalyze = async () => {
    if (!replyBody.trim()) {
      notifyWarning('请粘贴候选人回复内容')
      return
    }
    setAnalyzing(true)
    try {
      setIntent(await api.interviewReplyIntent(replyBody))
    } catch {
      // 拦截器已提示
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <Row gutter={16}>
      <Col xs={24} lg={10}>
        <Card title="面试调度">
          <Form form={form} layout="vertical" onFinish={onDraft}>
            <Form.Item name="job_id" label="岗位" rules={[{ required: true, message: '请选择岗位' }]}>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择岗位"
                options={jobs.map((j) => ({ value: j.id, label: j.title }))}
                notFoundContent={<Empty description="请先在岗位管理创建岗位" />}
              />
            </Form.Item>
            <Form.Item
              name="candidate_id"
              label="候选人"
              rules={[{ required: true, message: '请选择候选人' }]}
            >
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择候选人"
                options={candidates.map((c) => ({
                  value: c.id,
                  label: `${c.name}（${c.email || '无邮箱'}）`,
                }))}
                notFoundContent={<Empty description="请先上传简历" />}
              />
            </Form.Item>
            <Form.Item
              name="times"
              label="候选时间段（每行一个，最多 10 个）"
              rules={[{ required: true, message: '请填写候选时间段' }]}
            >
              <Input.TextArea
                rows={4}
                placeholder={'2026-09-15 10:00\n2026-09-16 14:30\n2026-09-17 09:30'}
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" icon={<FileTextOutlined />} loading={drafting}>
              生成邀请草稿
            </Button>
          </Form>

          <Divider />

          <Steps
            direction="vertical"
            size="small"
            current={step}
            items={[
              { title: '生成邀请草稿', description: 'LLM 按岗位与候选人撰写邮件（输出 PII 脱敏）' },
              { title: '确认并发送', description: 'Go 幂等锁 + MCP 邮件/日历' },
              { title: '回复意图分析', description: 'accept / propose_new_time / decline' },
            ]}
          />
        </Card>
      </Col>

      <Col xs={24} lg={14}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card
            title="邀请草稿预览"
            extra={
              draft && (
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  loading={sending}
                  onClick={() => void onSend()}
                >
                  确认发送
                </Button>
              )
            }
          >
            {!draft && <Empty description="填写左侧表单后点击「生成邀请草稿」" />}
            {draft && (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Descriptions
                  size="small"
                  column={1}
                  bordered
                  items={[
                    { key: 'to', label: '收件人', children: draft.candidate_email || candidateEmail(form.getFieldValue('candidate_id')) },
                    { key: 'name', label: '候选人', children: candidateName(form.getFieldValue('candidate_id')) },
                    { key: 'subject', label: '主题', children: draft.subject },
                  ]}
                />
                <Input.TextArea
                  value={draft.body}
                  autoSize={{ minRows: 8, maxRows: 16 }}
                  onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                />
                <div>
                  <Typography.Text type="secondary">发送时间段：</Typography.Text>
                  <Radio.Group
                    value={selectedTime}
                    onChange={(e) => setSelectedTime(e.target.value)}
                    style={{ display: 'block', marginTop: 8 }}
                  >
                    <Space direction="vertical">
                      {(draft.proposed_times ?? []).map((t) => (
                        <Radio key={t} value={t}>
                          {t}
                        </Radio>
                      ))}
                    </Space>
                  </Radio.Group>
                </div>
                {sendResult && (
                  <Alert
                    type="success"
                    showIcon
                    message={`发送状态：${sendResult.status ?? 'sent'}`}
                    description={
                      <Space direction="vertical" size={2}>
                        {sendResult.email_id && <Typography.Text>邮件 ID：{sendResult.email_id}</Typography.Text>}
                        {sendResult.calendar_event_id && (
                          <Typography.Text>日历事件：{sendResult.calendar_event_id}</Typography.Text>
                        )}
                      </Space>
                    }
                  />
                )}
              </Space>
            )}
          </Card>

          <Card title={<Space><RobotOutlined />候选人回复意图分析</Space>}>
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Input.TextArea
                rows={4}
                value={replyBody}
                onChange={(e) => setReplyBody(e.target.value)}
                placeholder="粘贴候选人邮件回复，例如：感谢邀请，但周五上午我有会议，能否改到周一上午 10 点？"
              />
              <Button onClick={() => void onAnalyze()} loading={analyzing}>
                分析意图
              </Button>
              {intent && (
                <Alert
                  type="info"
                  showIcon
                  message={
                    <Space>
                      <span>识别意图：</span>
                      <Tag color={INTENT_META[intent.intent]?.color}>
                        {INTENT_META[intent.intent]?.text ?? intent.intent}
                      </Tag>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={4}>
                      {intent.new_times?.length ? (
                        <Typography.Text>提取到新时间：{intent.new_times.join('、')}</Typography.Text>
                      ) : null}
                      {intent.message && <Typography.Text>{intent.message}</Typography.Text>}
                    </Space>
                  }
                />
              )}
            </Space>
          </Card>
        </Space>
      </Col>
    </Row>
  )
}
