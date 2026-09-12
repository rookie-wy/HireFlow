import { useCallback, useEffect, useState } from 'react'
import {
  Card,
  Upload,
  Table,
  Tag,
  Space,
  Button,
  Typography,
  Modal,
  Popconfirm,
  Descriptions,
  Empty,
  Alert,
} from 'antd'
import { InboxOutlined, ReloadOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { notifySuccess } from '../api/notify'
import { api } from '../api/client'
import type { Candidate } from '../api/types'
import { useAuthStore } from '../stores/auth'

export default function Candidates() {
  const role = useAuthStore((s) => s.role)
  const canDelete = role === 'manager' || role === 'admin'

  const [rows, setRows] = useState<Candidate[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [detail, setDetail] = useState<Candidate | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await api.listCandidates())
    } catch {
      // 拦截器已提示
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const uploadProps: UploadProps = {
    name: 'file',
    multiple: true,
    accept: '.pdf,.png,.jpg,.jpeg',
    showUploadList: false,
    async customRequest({ file, onSuccess, onError }) {
      setUploading(true)
      try {
        const r = await api.uploadCandidate(file as File)
        notifySuccess(`「${r.profile.name || '候选人'}」解析入库成功（向量分块 ${r.profile.vector_chunks ?? 0}）`)
        onSuccess?.(r)
        await load()
      } catch (e) {
        onError?.(e as Error)
      } finally {
        setUploading(false)
      }
    },
  }

  const onDelete = async (id: string) => {
    try {
      await api.deleteCandidate(id)
      notifySuccess('已删除')
      await load()
    } catch {
      // 拦截器已提示
    }
  }

  const columns: ColumnsType<Candidate> = [
    {
      title: '姓名',
      dataIndex: 'name',
      width: 120,
      render: (n: string, r) => <a onClick={() => setDetail(r)}>{n || '(未识别)'}</a>,
    },
    { title: '邮箱', dataIndex: 'email', ellipsis: true },
    { title: '电话', dataIndex: 'phone', width: 140 },
    {
      title: '技能标签',
      key: 'skills',
      render: (_, r) => {
        const skills = r.structured_json?.skills ?? []
        if (!skills.length) return <Typography.Text type="secondary">-</Typography.Text>
        return (
          <Space size={[4, 4]} wrap>
            {skills.slice(0, 6).map((s) => (
              <Tag color="blue" key={s}>
                {s}
              </Tag>
            ))}
            {skills.length > 6 && <Tag>+{skills.length - 6}</Tag>}
          </Space>
        )
      },
    },
    {
      title: '经历',
      key: 'exp',
      width: 80,
      render: (_, r) => `${r.structured_json?.work_experience?.length ?? 0} 段`,
    },
    {
      title: '入库时间',
      dataIndex: 'created_at',
      width: 180,
      render: (t: string) => new Date(t).toLocaleString(),
    },
    {
      title: '操作',
      key: 'op',
      width: 90,
      render: (_, r) =>
        canDelete ? (
          <Popconfirm title="删除该候选人（含向量）？" onConfirm={() => onDelete(r.id)}>
            <Button size="small" type="link" danger>
              删除
            </Button>
          </Popconfirm>
        ) : (
          <Typography.Text type="secondary">-</Typography.Text>
        ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="上传简历（PDF / PNG / JPG，单文件 ≤ 20MB）">
        <Upload.Dragger {...uploadProps} disabled={uploading}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽简历文件到此处上传</p>
          <p className="ant-upload-hint">
            上传后由 agent 服务提取文本 → LLM 结构化 → PII 脱敏 → 技能标准化 → 分块嵌入写入 Chroma
          </p>
        </Upload.Dragger>
        {uploading && (
          <Alert style={{ marginTop: 12 }} type="info" showIcon message="解析中：LLM 抽取 + BGE-M3 向量化..." />
        )}
      </Card>

      <Card
        title={`候选人库（${rows.length}）`}
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            刷新
          </Button>
        }
      >
        <Table<Candidate>
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无候选人，请先上传简历" /> }}
        />
      </Card>

      <Modal
        open={Boolean(detail)}
        title={detail?.name || '候选人详情'}
        footer={null}
        width={720}
        onCancel={() => setDetail(null)}
      >
        {detail && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Descriptions
              bordered
              size="small"
              column={2}
              items={[
                { key: 'id', label: 'ID', children: <Typography.Text copyable>{detail.id}</Typography.Text>, span: 2 },
                { key: 'email', label: '邮箱', children: detail.email || '-' },
                { key: 'phone', label: '电话', children: detail.phone || '-' },
                {
                  key: 'skills',
                  label: '技能',
                  span: 2,
                  children: (detail.structured_json?.skills ?? []).join('、') || '-',
                },
              ]}
            />
            <Typography.Title level={5} style={{ margin: 0 }}>
              工作经历
            </Typography.Title>
            <Table
              size="small"
              rowKey={(r) => `${r.company}-${r.start_date}`}
              pagination={false}
              dataSource={detail.structured_json?.work_experience ?? []}
              columns={[
                { title: '公司', dataIndex: 'company' },
                { title: '职位', dataIndex: 'title' },
                {
                  title: '时间',
                  key: 'time',
                  render: (_, r) => `${r.start_date || '?'} ~ ${r.end_date || '至今'}`,
                },
              ]}
            />
            <Typography.Title level={5} style={{ margin: 0 }}>
              教育经历
            </Typography.Title>
            <Table
              size="small"
              rowKey={(r) => `${r.school}-${r.degree}`}
              pagination={false}
              dataSource={detail.structured_json?.education ?? []}
              columns={[
                { title: '学校', dataIndex: 'school' },
                { title: '学历', dataIndex: 'degree' },
                { title: '专业', dataIndex: 'major' },
              ]}
            />
            {detail.resume_text && (
              <Typography.Paragraph
                style={{ whiteSpace: 'pre-wrap', maxHeight: 220, overflow: 'auto', background: '#fafafa', padding: 12 }}
              >
                {detail.resume_text}
              </Typography.Paragraph>
            )}
          </Space>
        )}
      </Modal>
    </Space>
  )
}
