import { useEffect } from 'react'
import type { ReactElement } from 'react'
import { App as AntdApp } from 'antd'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuthStore } from './stores/auth'
import { bindMessageApi } from './api/notify'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Jobs from './pages/Jobs'
import Candidates from './pages/Candidates'
import Screening from './pages/Screening'
import Interview from './pages/Interview'

/** 把 antd App 的 message 实例注入到非组件模块（axios 拦截器等） */
function MessageBridge() {
  const { message } = AntdApp.useApp()
  useEffect(() => {
    bindMessageApi(message)
    return () => bindMessageApi(null)
  }, [message])
  return null
}

/** 登录守卫：未登录一律回登录页。 */
function RequireAuth({ children }: { children: ReactElement }) {
  const token = useAuthStore((s) => s.token)
  const location = useLocation()
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

export default function App() {
  return (
    <>
      <MessageBridge />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/screening" replace />} />
          <Route path="jobs" element={<Jobs />} />
          <Route path="candidates" element={<Candidates />} />
          <Route path="screening" element={<Screening />} />
          <Route path="interview" element={<Interview />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
