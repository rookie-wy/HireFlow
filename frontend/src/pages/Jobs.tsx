import { useCallback, useEffect, useState } from 'react'
import {
  Card,
  Form,
  Input,
  Button,
  Select,
  Table,
  Tag,
  Space,
  Typography,
  Modal,
  Popconfirm,
  Descriptions,
  Empty,
  Divider,
  Row,
  Col,
  InputNumber,
  Alert,
} from 'antd'
import { PlusOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { notifySuccess } from '../api/notify'
import { api } from '../api/client'
import type { Job, JobDescription } from '../api/types'
import { useAuthStore } from '../stores/auth'

const CATEGORY_COLOR: Record<string, string> = {
  tech: 'blue',
  management: 'purple',
  design: 'magenta',
  general: 'default',
}

function RequirementTags({ items, color }: { items?: string[]; color: string }) {
  if (!items?.length) return <Typography.Text type="secondary">无</Typography.Text>
  return (
    <Space size={[4, 4]} wrap>
      {items.map((t, i) => (
        <Tag color={color} key={`${t}-${i}`}>
          {t}
        </Tag>
      ))}
    </Space>
  )
}

export default function Jobs() {
  const navigate = useNavigate()
  const role = useAuthStore((s) => s.role)
  const canDelete = role === 'manager' || role === 'admin'

  const [form] = Form.useForm<{ jd_text: string; language: string }>()
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [parsed, setParsed] = useState<JobDescription | null>(null)
  const [detail, setDetail] = useState<Job | null>(null)
  const [overrideForm] = Form.useForm<Record<string, number>>()
  const [savingOverrides, setSavingOverrides] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setJobs(await api.listJobs())
    } catch {
      // 拦截器已提示
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const onCreate = async (v: { jd_text: string; language: string }) => {
    setSubmitting(true)
    try {
      const r = await api.createJob(v.jd_text, v.language)
      setParsed(r.parsed)
      notifySuccess(`岗位「${r.job.title}」创建成功`)
      form.resetFields()
      await load()
    } catch {
      // 拦截器已提示
    } finally {
      setSubmitting(false)
    }
  }

  const onDelete = async (id: string) => {
    try {
      await api.deleteJob(id)
      notifySuccess('已删除')
      await load()
    } catch {
      // 拦截器已提示
    }
  }

  /** 打开详情时把已有覆盖回填到表单 */
  const openDetail = (job: Job) => {
    setDetail(job)
    const w = job.weights_override ?? {}
    const sc = job.screen_overrides ?? {}
    overrideForm.setFieldsValue({
      interviewer: w.interviewer,
      skill_evaluator: w.skill_evaluator,
      culture_fit: w.culture_fit,
      stability_analyzer: w.stability_analyzer,
      rag_top_k: sc.rag_top_k as number | undefined,
      rerank_threshold_cosine: sc.rerank_threshold_cosine as number | undefined,
    })
  }

  const saveOverrides = async (clear = false) => {
    if (!detail) return
    setSavingOverrides(true)
    try {
      const v = clear ? {} : overrideForm.getFieldsValue()
      const weights: Record<string, number> = {}
      for (const k of ['interviewer', 'skill_evaluator', 'culture_fit', 'stability_analyzer']) {
        const num = v[k]
        if (typeof num === 'number' && num > 0) weights[k] = num
      }
      const screen: Record<string, number> = {}
      for (const k of ['rag_top_k', 'rerank_threshold_cosine']) {
        const num = v[k]
        if (typeof num === 'number' && num > 0) screen[k] = num
      }
      const updated = await api.updateJobOverrides(detail.id, weights, screen)
      notifySuccess(clear ? '已清除岗位覆盖，恢复系统默认' : '岗位配置已保存（相关缓存将自动失效）')
      setDetail(updated)
      await load()
    } catch {
      // 拦截器已提示（权重和不为 1 等校验错误会显示后端消息）
    } finally {
      setSavingOverrides(false)
    }
  }

  const columns: ColumnsType<Job> = [
    {
      title: '岗位名称',
      dataIndex: 'title',
      render: (t: string, r) => (
        <a onClick={() => openDetail(r)}>{t || '(未命名)'}</a>
      ),
    },
    {
      title: '类别',
      dataIndex: 'job_category',
      width: 100,
      render: (c: string) => <Tag color={CATEGORY_COLOR[c] ?? 'default'}>{c || '-'}</Tag>,
    },
    {
      title: '硬性要求',
      key: 'hard',
      width: 90,
      render: (_, r) => `${r.jd_json?.hard_requirements?.length ?? 0} 条`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (t: string) => new Date(t).toLocaleString(),
    },
    {
      title: '操作',
      key: 'op',
      width: 170,
      render: (_, r) => (
        <Space size="small">
          <Button
            size="small"
            type="link"
            icon={<ThunderboltOutlined />}
            onClick={() => navigate('/screening', { state: { jobId: r.id } })}
          >
            去筛选
          </Button>
          {canDelete && (
            <Popconfirm title="删除该岗位？" onConfirm={() => onDelete(r.id)}>
              <Button size="small" type="link" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title="新建岗位（JD 文本 → LLM 结构化解析）"
        extra={
          <Typography.Text type="secondary">
            解析出硬性/软性要求、技能图谱与岗位类别，供粗筛硬过滤与专家 Agent 选组使用
          </Typography.Text>
        }
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={onCreate}
          initialValues={{ language: 'zh' }}
        >
          <Form.Item
            name="jd_text"
            label="JD 原文"
            rules={[{ required: true, message: '请输入 JD 文本' }]}
          >
            <Input.TextArea
              rows={8}
              placeholder="粘贴完整 JD 文本，例如：岗位职责、任职要求、技能栈等"
              showCount
              maxLength={50000}
            />
          </Form.Item>
          <Space>
            <Form.Item name="language" label="语言" style={{ marginBottom: 0 }}>
              <Select
                style={{ width: 120 }}
                options={[
                  { value: 'zh', label: '中文' },
                  { value: 'en', label: 'English' },
                ]}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={submitting}>
                创建并解析
              </Button>
            </Form.Item>
          </Space>
        </Form>

        {parsed && (
          <Descriptions
            bordered
            size="small"
            column={1}
            style={{ marginTop: 16 }}
            title="最近一次解析结果"
            items={[
              { key: 'title', label: '岗位标题', children: parsed.title },
              {
                key: 'cat',
                label: '岗位类别',
                children: <Tag color={CATEGORY_COLOR[parsed.job_category] ?? 'default'}>{parsed.job_category}</Tag>,
              },
              {
                key: 'hard',
                label: '硬性要求',
                children: <RequirementTags items={parsed.hard_requirements} color="red" />,
              },
              {
                key: 'soft',
                label: '软性要求',
                children: <RequirementTags items={parsed.soft_requirements} color="green" />,
              },
              {
                key: 'skill',
                label: '技能图谱',
                children: <RequirementTags items={parsed.skill_graph} color="blue" />,
              },
            ]}
          />
        )}
      </Card>

      <Card
        title={`岗位列表（${jobs.length}）`}
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            刷新
          </Button>
        }
      >
        <Table<Job>
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={jobs}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无岗位，请先创建" /> }}
        />
      </Card>

      <Modal
        open={Boolean(detail)}
        title={detail?.title || '岗位详情'}
        footer={null}
        width={860}
        onCancel={() => setDetail(null)}
      >
        {detail && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Descriptions
              bordered
              size="small"
              column={1}
              items={[
                { key: 'id', label: 'ID', children: <Typography.Text copyable>{detail.id}</Typography.Text> },
                { key: 'cat', label: '类别', children: detail.job_category },
                {
                  key: 'hard',
                  label: '硬性要求',
                  children: <RequirementTags items={detail.jd_json?.hard_requirements} color="red" />,
                },
                {
                  key: 'soft',
                  label: '软性要求',
                  children: <RequirementTags items={detail.jd_json?.soft_requirements} color="green" />,
                },
                {
                  key: 'skill',
                  label: '技能图谱',
                  children: <RequirementTags items={detail.jd_json?.skill_graph} color="blue" />,
                },
              ]}
            />
            <Divider style={{ margin: '4px 0' }}>岗位级配置（仅 manager+ 可改；留空用系统默认）</Divider>
            <Alert
              type="info"
              showIcon
              message="权重决定各专家在仲裁中的占比；检索参数影响粗筛召回与重排阈值"
              description={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  权重需为正数且**总和为 1**；只填想调的专家时，未填的专家权重按 0 处理（不参与仲裁）。
                  修改后已缓存的精筛结论会自动失效并重算。
                </Typography.Text>
              }
            />
            <Form form={overrideForm} layout="vertical" size="small">
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item label="面试官权重" name="interviewer">
                    <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} placeholder="默认 0.35" disabled={!canDelete} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="技能评估权重" name="skill_evaluator">
                    <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} placeholder="默认 0.35" disabled={!canDelete} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="文化契合权重" name="culture_fit">
                    <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} placeholder="默认 0.15" disabled={!canDelete} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="稳定性权重" name="stability_analyzer">
                    <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} placeholder="默认 0.15" disabled={!canDelete} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="粗筛召回数 rag_top_k" name="rag_top_k">
                    <InputNumber min={1} max={200} style={{ width: '100%' }} placeholder="默认 30" disabled={!canDelete} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="余弦重排阈值" name="rerank_threshold_cosine">
                    <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} placeholder="默认 0.55" disabled={!canDelete} />
                  </Form.Item>
                </Col>
              </Row>
              <Space>
                <Button type="primary" size="small" loading={savingOverrides} disabled={!canDelete} onClick={() => void saveOverrides()}>
                  保存岗位配置
                </Button>
                <Button size="small" disabled={!canDelete} onClick={() => void saveOverrides(true)}>
                  清除覆盖（恢复默认）
                </Button>
                {!canDelete && <Typography.Text type="secondary">当前角色无修改权限</Typography.Text>}
              </Space>
            </Form>

            <Divider style={{ margin: '4px 0' }}>JD 原文</Divider>
            <Typography.Paragraph
              style={{ whiteSpace: 'pre-wrap', maxHeight: 260, overflow: 'auto', background: '#fafafa', padding: 12 }}
            >
              {detail.jd_text}
            </Typography.Paragraph>
          </Space>
        )}
      </Modal>
    </Space>
  )
}
