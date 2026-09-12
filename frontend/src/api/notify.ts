/**
 * antd v5 的 message 静态方法无法消费 ConfigProvider 主题上下文（控制台会告警：
 * "Static function can not consume context like dynamic theme"）。
 * 这里由 App 组件在挂载时把 App.useApp() 的实例注入进来，非组件模块（axios 拦截器）统一走 notify。
 */
import { message as staticMessage } from 'antd'
import type { MessageInstance } from 'antd/es/message/interface'

let instance: MessageInstance | null = null

export function bindMessageApi(api: MessageInstance | null) {
  instance = api
}

export function notifyError(content: string) {
  void (instance ?? staticMessage).error(content)
}

export function notifySuccess(content: string) {
  void (instance ?? staticMessage).success(content)
}

export function notifyWarning(content: string) {
  void (instance ?? staticMessage).warning(content)
}
