import { useState } from 'react'
import { Card, Form, Input, Button, Tabs, Typography, Space } from 'antd'
import { LockOutlined, UserOutlined, ApartmentOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { notifySuccess } from '../api/notify'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'

export default function Login() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState('login')

  const onLogin = async (v: { username: string; password: string; tenant_id: string }) => {
    setLoading(true)
    try {
      const r = await api.login(v.username, v.password, v.tenant_id)
      login(r)
      notifySuccess('登录成功')
      navigate('/screening', { replace: true })
    } catch {
      // 拦截器已提示
    } finally {
      setLoading(false)
    }
  }

  const onRegister = async (v: {
    username: string
    password: string
    tenant_id: string
    role: string
  }) => {
    setLoading(true)
    try {
      const r = await api.register(v.username, v.password, v.tenant_id, v.role)
      login(r)
      notifySuccess('注册成功，已自动登录')
      navigate('/screening', { replace: true })
    } catch {
      // 拦截器已提示
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #1d39c4 0%, #2f54eb 40%, #722ed1 100%)',
      }}
    >
      <Card style={{ width: 420, boxShadow: '0 12px 32px rgba(0,0,0,.25)' }}>
        <Space direction="vertical" align="center" style={{ width: '100%', marginBottom: 12 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            AI 智能招聘助手
          </Typography.Title>
          <Typography.Text type="secondary">多 Agent 圆桌讨论 · 企业级简历筛选</Typography.Text>
        </Space>

        <Tabs
          activeKey={tab}
          onChange={setTab}
          centered
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <Form
                  layout="vertical"
                  onFinish={onLogin}
                  initialValues={{ tenant_id: 'company_a', username: 'hr_admin' }}
                >
                  <Form.Item name="tenant_id" label="租户" rules={[{ required: true }]}>
                    <Input prefix={<ApartmentOutlined />} placeholder="company_a" />
                  </Form.Item>
                  <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
                    <Input prefix={<UserOutlined />} placeholder="hr_admin" />
                  </Form.Item>
                  <Form.Item name="password" label="密码" rules={[{ required: true }]}>
                    <Input.Password prefix={<LockOutlined />} placeholder="password123" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    登录
                  </Button>
                </Form>
              ),
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <Form
                  layout="vertical"
                  onFinish={onRegister}
                  initialValues={{ tenant_id: 'company_a', role: 'hr' }}
                >
                  <Form.Item name="tenant_id" label="租户" rules={[{ required: true }]}>
                    <Input prefix={<ApartmentOutlined />} />
                  </Form.Item>
                  <Form.Item
                    name="username"
                    label="用户名"
                    rules={[{ required: true, min: 3, message: '至少 3 个字符' }]}
                  >
                    <Input prefix={<UserOutlined />} />
                  </Form.Item>
                  <Form.Item
                    name="password"
                    label="密码"
                    rules={[{ required: true, min: 8, message: '至少 8 个字符' }]}
                  >
                    <Input.Password prefix={<LockOutlined />} />
                  </Form.Item>
                  <Form.Item name="role" label="角色">
                    <Input placeholder="hr / manager / admin" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    注册并登录
                  </Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
