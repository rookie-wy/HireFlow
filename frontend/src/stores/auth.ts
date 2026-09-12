import { create } from 'zustand'
import type { LoginResult, Role } from '../api/types'

interface AuthState {
  token: string
  userId: string
  tenantId: string
  role: Role | ''
  login: (r: LoginResult) => void
  logout: () => void
}

interface Persisted {
  token: string
  user_id: string
  tenant_id: string
  role: Role
}

const STORAGE_KEY = 'ai-recruit-auth'

function load(): Partial<Persisted> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Persisted) : {}
  } catch {
    return {}
  }
}

const persisted = load()

export const useAuthStore = create<AuthState>((set) => ({
  token: persisted.token ?? '',
  userId: persisted.user_id ?? '',
  tenantId: persisted.tenant_id ?? '',
  role: persisted.role ?? '',
  login: (r) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(r))
    set({ token: r.access_token, userId: r.user_id, tenantId: r.tenant_id, role: r.role })
  },
  logout: () => {
    localStorage.removeItem(STORAGE_KEY)
    set({ token: '', userId: '', tenantId: '', role: '' })
  },
}))

export const isAuthed = () => Boolean(useAuthStore.getState().token)
