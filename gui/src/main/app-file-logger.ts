import fs from 'node:fs'
import path from 'node:path'
import { app } from 'electron'

function resolvedLogDir(): string {
  return path.join(app.getPath('userData'), 'logs')
}

function ensureLogDir(): void {
  const dir = resolvedLogDir()
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true })
  }
}

function logFilePathForToday(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return path.join(resolvedLogDir(), `youtube-scrape-${y}-${m}-${day}.log`)
}

/** Absolute path to the directory containing rotating daily log files. */
export function getAppLogDirectory(): string {
  try {
    if (!app.isReady()) {
      return ''
    }
    ensureLogDir()
    return resolvedLogDir()
  } catch {
    return ''
  }
}

/**
 * Append one UTF-8 line to today's log under userData/logs.
 * No-ops if app is not ready (avoid throwing from getPath during startup).
 */
export function appendAppFileLog(
  source: 'main' | 'renderer' | 'python',
  level: string,
  message: string,
  detail?: unknown
): void {
  try {
    if (!app.isReady()) {
      return
    }
    ensureLogDir()
    const ts = new Date().toISOString()
    const suffix =
      detail !== undefined
        ? `\t${typeof detail === 'string' ? detail : JSON.stringify(detail)}`
        : ''
    const line = `${ts}\t[${source}]\t[${String(level).toUpperCase()}]\t${message}${suffix}\n`
    fs.appendFileSync(logFilePathForToday(), line, 'utf8')
  } catch {
    // never throw from logging
  }
}
