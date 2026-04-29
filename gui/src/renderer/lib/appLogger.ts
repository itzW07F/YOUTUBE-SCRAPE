export function appLog(
  level: 'debug' | 'info' | 'warn' | 'error',
  scope: string,
  message: string,
  detail?: unknown
): void {
  if (typeof window === 'undefined' || !window.electronAPI?.appendAppLog) {
    return
  }
  void window.electronAPI.appendAppLog(level, scope, message, detail)
}
