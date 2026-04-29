import fs from 'node:fs'
import path from 'node:path'
import { app } from 'electron'
import { appendAppFileLog } from './app-file-logger'

/** Persist to userData/logs; also gui/.dev-electron.log in development. */
export function devLogLine(message: string): void {
  appendAppFileLog('main', 'info', message)
  if (app.isPackaged) {
    return
  }
  try {
    const file = path.join(__dirname, '..', '..', '.dev-electron.log')
    const line = `${new Date().toISOString()} ${message}\n`
    fs.appendFileSync(file, line, 'utf8')
  } catch {
    // ignore
  }
}
