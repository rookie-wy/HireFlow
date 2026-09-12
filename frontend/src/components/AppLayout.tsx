import { useMemo } from 'react'
import { Layout, Menu, Tag, Space, Button, Typography } from 'antd'
import {
  AuditOutlined,
  LogoutOutlined,
  SolutionOutlined,
  TeamOutlined,
  UserOutlined,
  ScheduleOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/auth'

const { Header, Sider, Content } = Layout

const ROLE_LABEL: Record<string, string> = { hr: 'HR', manager: '经理', admin: '管理员' }

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { tenantId, role, userId, logout } = useAuthStore()

  const items = useMemo(
    () => [
      { key: '/screening', icon: <AuditOutlined />, label: '智能筛选' },
      { key: '/jobs', icon: <SolutionOutlined />, label: '岗位管理' },
      { key: '/candidates', icon: <TeamOutlined />, label: '候选人' },
      { key: '/interview', icon: <ScheduleOutlined />, label: '面试调度' },
    ],
    [],
  )

  const selected = items.find((i) => location.pathname.startsWith(i.key))?.key ?? '/screening'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="dark" breakpoint="lg" collapsedWidth={64}>
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 600,
            letterSpacing: 1,
          }}
        >
          AI 招聘
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            paddingInline: 20,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Typography.Text strong>企业级 AI 简历筛选与面试调度平台</Typography.Text>
          <Space size="middle">
            <Tag color="blue">租户 {tenantId || '-'}</Tag>
            <Tag icon={<UserOutlined />} color="geekblue">
              {ROLE_LABEL[role] ?? role}
            </Tag>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {userId.slice(0, 8)}
            </Typography.Text>
            <Button
              size="small"
              icon={<LogoutOutlined />}
              onClick={() => {
                logout()
                navigate('/login')
              }}
            >
              退出
            </Button>
          </Space>
        </Header>
        <Content style={{ padding: 20 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
