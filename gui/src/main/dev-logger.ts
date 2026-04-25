import fs from 'node:fs'
import path from 'node:path'
import { app } from 'electron'

/** Append a line to gui/.dev-electron.log in development only. */
export function devLogLine(message: string): void {
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
