import { spawn, ChildProcess } from 'child_process'
import { fileURLToPath } from 'node:url'
import { app } from 'electron'
import path from 'path'
import net from 'net'
import { devLogLine } from './dev-logger'

interface ServerConfig {
  host: string
  port: number
  pythonPath: string
  apiModulePath: string
}

interface ServerStatus {
  running: boolean
  port?: number
  url?: string
  pid?: number
}

interface LogEntry {
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
  timestamp: string
}

export class PythonBridge {
  private process: ChildProcess | null = null
  private status: ServerStatus = { running: false }
  private config: ServerConfig
  private logListeners: ((log: LogEntry) => void)[] = []
  private isDev = !app.isPackaged

  constructor() {
    this.config = {
      host: '127.0.0.1',
      port: 8000,
      pythonPath: this.getPythonPath(),
      apiModulePath: this.getApiModulePath()
    }
  }

  private getPythonPath(): string {
    // In production, use bundled Python
    if (app.isPackaged) {
      const platform = process.platform
      if (platform === 'win32') {
        return path.join(process.resourcesPath, 'python', 'python.exe')
      }
      return path.join(process.resourcesPath, 'python', 'bin', 'python')
    }
    // In development, use system Python from venv or PATH
    return process.env.PYTHON_PATH || 'python'
  }

  /** For main-process logging: resolved server.py path, python binary, and spawn cwd. */
  getSpawnContextForLog(): { apiModulePath: string; pythonPath: string; spawnCwd: string } {
    const apiModulePath = this.getApiModulePath()
    return {
      apiModulePath,
      pythonPath: this.getPythonPath(),
      spawnCwd: !app.isPackaged ? this.getDevRepoRootForSpawn() : path.dirname(apiModulePath)
    }
  }

  private getApiModulePath(): string {
    if (app.isPackaged) {
      return path.join(process.resourcesPath, 'src', 'youtube_scrape', 'api', 'server.py')
    }
    // Dev: main process bundle is at gui/out/main/index.js — repo root is three levels up.
    // (app.getAppPath() is often gui/ itself; join(.., .., "src", ...) would miss the project.)
    const mainDir = path.dirname(fileURLToPath(import.meta.url))
    return path.join(mainDir, '..', '..', '..', 'src', 'youtube_scrape', 'api', 'server.py')
  }

  private async findAvailablePort(startPort: number): Promise<number> {
    return new Promise((resolve, reject) => {
      const server = net.createServer()
      server.listen(startPort, this.config.host, () => {
        const { port } = server.address() as net.AddressInfo
        server.close(() => resolve(port))
      })
      server.on('error', (err: NodeJS.ErrnoException) => {
        if (err.code === 'EADDRINUSE') {
          this.findAvailablePort(startPort + 1).then(resolve, reject)
        } else {
          reject(err)
        }
      })
    })
  }

  /** When running from the dev bundle, repo root (three levels up from out/main) so Python `output/<id>/` matches the GUI. */
  private getDevRepoRootForSpawn(): string {
    const mainDir = path.dirname(fileURLToPath(import.meta.url))
    return path.resolve(path.join(mainDir, '..', '..', '..'))
  }

  async start(allowedOutputRoots?: string[]): Promise<{ success: boolean; error?: string }> {
    if (this.status.running) {
      return { success: true }
    }

    let stderrTail = ''

    try {
      // Find available port
      const port = await this.findAvailablePort(this.config.port)
      this.config.port = port

      // Dev: CWD was api/ (next to server.py) so files landed in src/.../api/output/ while the app scans <repo>/output.
      // Use project root in development so abspath "output"/video_id matches the GUI and getAllowedOutputRoots.
      const spawnCwd = !app.isPackaged
        ? this.getDevRepoRootForSpawn()
        : path.dirname(this.config.apiModulePath)
      const args = [
        '-u', // Unbuffered output for real-time logs
        this.config.apiModulePath,
        '--host', this.config.host,
        '--port', port.toString()
      ]
      const cmdline = [this.config.pythonPath, ...args].map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(' ')
      devLogLine(
        `spawn: cwd=${spawnCwd} | ${cmdline}`
      )

      const roots = [...new Set((allowedOutputRoots ?? []).map((p) => path.resolve(p.trim())).filter(Boolean))]

      // Prepare environment
      const env: NodeJS.ProcessEnv = {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        API_HOST: this.config.host,
        API_PORT: port.toString(),
        NODE_ENV: this.isDev ? 'development' : 'production'
      }
      if (roots.length > 0) {
        env.YOUTUBE_SCRAPE_OUTPUT_ROOTS = roots.join(path.delimiter)
        env.OUTPUT_DIR = roots[0]
      } else {
        env.OUTPUT_DIR = path.resolve(spawnCwd, 'output')
      }

      this.process = spawn(this.config.pythonPath, args, {
        env,
        cwd: spawnCwd,
        stdio: ['pipe', 'pipe', 'pipe']
      })

      // Handle process events
      this.process.stdout?.on('data', (data: Buffer) => {
        const message = data.toString().trim()
        if (message) {
          this.emitLog({ level: 'info', message, timestamp: new Date().toISOString() })
        }
      })

      this.process.stderr?.on('data', (data: Buffer) => {
        const message = data.toString()
        stderrTail = (stderrTail + message).slice(-2048)
        const trim = message.trim()
        if (trim) {
          this.emitLog({ level: 'error', message: trim, timestamp: new Date().toISOString() })
        }
      })

      this.process.on('error', (error: Error) => {
        this.emitLog({ level: 'error', message: `Process error: ${error.message}`, timestamp: new Date().toISOString() })
        devLogLine(`spawn process error: ${error.message}`)
        this.status = { running: false }
      })

      this.process.on('exit', (code: number | null) => {
        this.emitLog({ level: 'info', message: `Python server exited with code ${code}`, timestamp: new Date().toISOString() })
        if (code !== 0 && code !== null && stderrTail) {
          devLogLine(`python exit ${code} stderr (tail): ${stderrTail.slice(-2000)}`)
        }
        this.status = { running: false }
        this.process = null
      })

      // Wait for server to be ready
      await this.waitForServer(port)

      this.status = {
        running: true,
        port,
        url: `http://${this.config.host}:${port}`,
        pid: this.process.pid
      }

      this.emitLog({ level: 'info', message: `Python server started on port ${port}`, timestamp: new Date().toISOString() })

      return { success: true }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      this.emitLog({ level: 'error', message: `Failed to start server: ${errorMessage}`, timestamp: new Date().toISOString() })
      if (stderrTail) {
        devLogLine(`health wait failed; python stderr (tail): ${stderrTail.slice(-2000)}`)
      }
      return { success: false, error: errorMessage }
    }
  }

  private async waitForServer(port: number, timeout = 30000): Promise<void> {
    const startTime = Date.now()
    
    while (Date.now() - startTime < timeout) {
      try {
        const response = await fetch(`http://${this.config.host}:${port}/health`)
        if (response.ok) {
          return
        }
      } catch {
        // Server not ready yet
      }
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    
    throw new Error(`Server failed to start within ${timeout}ms`)
  }

  async stop(): Promise<{ success: boolean; error?: string }> {
    if (!this.process || !this.status.running) {
      return { success: true }
    }

    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        this.process?.kill('SIGKILL')
        this.status = { running: false }
        resolve({ success: false, error: 'Force killed after timeout' })
      }, 10000)

      this.process?.on('exit', () => {
        clearTimeout(timeout)
        this.status = { running: false }
        resolve({ success: true })
      })

      // Try graceful shutdown first
      this.process?.kill('SIGTERM')
    })
  }

  getStatus(): ServerStatus {
    return { ...this.status }
  }

  onLog(callback: (log: LogEntry) => void): () => void {
    this.logListeners.push(callback)
    return () => {
      const index = this.logListeners.indexOf(callback)
      if (index > -1) {
        this.logListeners.splice(index, 1)
      }
    }
  }

  private emitLog(log: LogEntry): void {
    this.logListeners.forEach(listener => listener(log))
  }
}

export const pythonBridge = new PythonBridge()
