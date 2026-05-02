import { spawn, ChildProcess } from 'child_process'
import fs from 'node:fs'
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

export type PythonSpawnEnvExtras = Partial<{
  YOUTUBE_SCRAPE_MAX_CONCURRENT_SCRAPE_JOBS: string
  YOUTUBE_SCRAPE_FFMPEG_THREADS: string
  YOUTUBE_SCRAPE_ANALYTICS_LLM_PROVIDER: string
  YOUTUBE_SCRAPE_ANALYTICS_OLLAMA_ENABLED: string
  YOUTUBE_SCRAPE_OLLAMA_BASE_URL: string
  YOUTUBE_SCRAPE_OLLAMA_MODEL: string
  YOUTUBE_SCRAPE_OPENAI_COMPATIBLE_BASE_URL: string
  YOUTUBE_SCRAPE_OPENAI_COMPATIBLE_API_KEY: string
  YOUTUBE_SCRAPE_OPENAI_COMPATIBLE_MODEL: string
  YOUTUBE_SCRAPE_ANTHROPIC_BASE_URL: string
  YOUTUBE_SCRAPE_ANTHROPIC_API_KEY: string
  YOUTUBE_SCRAPE_ANTHROPIC_MODEL: string
  YOUTUBE_SCRAPE_GOOGLE_GEMINI_API_KEY: string
  YOUTUBE_SCRAPE_GOOGLE_GEMINI_MODEL: string
  YOUTUBE_SCRAPE_ANALYTICS_RAG_ENABLED: string
  YOUTUBE_SCRAPE_OLLAMA_EMBED_MODEL: string
  YOUTUBE_SCRAPE_YOUTUBE_DATA_API_ENABLED: string
  YOUTUBE_SCRAPE_YOUTUBE_DATA_API_KEY: string
}>

type ElectronStoreLike = { get(key: string, defaultValue?: unknown): unknown }

const ANALYTICS_LLM_PROVIDERS = ['ollama', 'openai_compatible', 'anthropic', 'google_gemini'] as const
type AnalyticsLlmProviderId = (typeof ANALYTICS_LLM_PROVIDERS)[number]

function stripTrailingSlashes(s: string): string {
  const t = s.trim()
  if (!t) {
    return t
  }
  return t.replace(/\/+$/, '')
}

function storeString(v: unknown, fallback: string): string {
  if (typeof v === 'string' && v.trim()) {
    return v.trim()
  }
  return fallback
}

function analyticsLlmProviderFromStore(raw: unknown): AnalyticsLlmProviderId {
  return ANALYTICS_LLM_PROVIDERS.includes(raw as AnalyticsLlmProviderId)
    ? (raw as AnalyticsLlmProviderId)
    : 'ollama'
}

function storeBool(v: unknown, defaultValue: boolean): boolean {
  if (v === false) {
    return false
  }
  if (v === true) {
    return true
  }
  return defaultValue
}

function clampInt(n: unknown, fallback: number, min: number, max: number): number {
  const x = typeof n === 'number' ? n : typeof n === 'string' ? Number.parseInt(n, 10) : Number.NaN
  if (!Number.isFinite(x)) {
    return fallback
  }
  return Math.min(max, Math.max(min, Math.floor(x)))
}

/** Build env overrides for the Python scrape API from Electron store. */
export function youtubeScrapeSpawnEnvExtras(store: ElectronStoreLike): PythonSpawnEnvExtras {
  const jc = clampInt(store.get('downloadMaxConcurrentJobs', 2), 2, 1, 16)
  const ft = clampInt(store.get('ffmpegThreads', 0), 0, 0, 64)
  const provider = analyticsLlmProviderFromStore(store.get('analyticsLlmProvider', 'ollama'))
  const analyticsLlmOn = storeBool(store.get('analyticsOllamaEnabled', true), true)
  const ragOn = storeBool(store.get('analyticsRagEnabled', false), false)
  const youtubeDataApiOn = storeBool(store.get('youtubeDataApiEnabled', false), false)
  return {
    YOUTUBE_SCRAPE_MAX_CONCURRENT_SCRAPE_JOBS: String(jc),
    YOUTUBE_SCRAPE_FFMPEG_THREADS: String(ft),
    YOUTUBE_SCRAPE_ANALYTICS_LLM_PROVIDER: provider,
    YOUTUBE_SCRAPE_ANALYTICS_OLLAMA_ENABLED: analyticsLlmOn ? 'true' : 'false',
    YOUTUBE_SCRAPE_OLLAMA_BASE_URL: stripTrailingSlashes(
      storeString(store.get('ollamaBaseUrl', ''), 'http://127.0.0.1:11434')
    ),
    YOUTUBE_SCRAPE_OLLAMA_MODEL: storeString(store.get('ollamaModel', ''), 'gpt-oss:20b'),
    YOUTUBE_SCRAPE_OPENAI_COMPATIBLE_BASE_URL: stripTrailingSlashes(
      storeString(store.get('openaiCompatibleBaseUrl', ''), 'https://api.openai.com/v1')
    ),
    YOUTUBE_SCRAPE_OPENAI_COMPATIBLE_API_KEY: storeString(store.get('openaiCompatibleApiKey', ''), ''),
    YOUTUBE_SCRAPE_OPENAI_COMPATIBLE_MODEL: storeString(
      store.get('openaiCompatibleModel', ''),
      'gpt-4o-mini'
    ),
    YOUTUBE_SCRAPE_ANTHROPIC_BASE_URL: stripTrailingSlashes(
      storeString(store.get('anthropicBaseUrl', ''), 'https://api.anthropic.com')
    ),
    YOUTUBE_SCRAPE_ANTHROPIC_API_KEY: storeString(store.get('anthropicApiKey', ''), ''),
    YOUTUBE_SCRAPE_ANTHROPIC_MODEL: storeString(
      store.get('anthropicModel', ''),
      'claude-sonnet-4-20250514'
    ),
    YOUTUBE_SCRAPE_GOOGLE_GEMINI_API_KEY: storeString(store.get('googleGeminiApiKey', ''), ''),
    YOUTUBE_SCRAPE_GOOGLE_GEMINI_MODEL: storeString(
      store.get('googleGeminiModel', ''),
      'gemini-2.0-flash'
    ),
    YOUTUBE_SCRAPE_ANALYTICS_RAG_ENABLED: ragOn ? 'true' : 'false',
    YOUTUBE_SCRAPE_OLLAMA_EMBED_MODEL: storeString(store.get('ollamaEmbedModel', ''), 'nomic-embed-text'),
    YOUTUBE_SCRAPE_YOUTUBE_DATA_API_ENABLED: youtubeDataApiOn ? 'true' : 'false',
    YOUTUBE_SCRAPE_YOUTUBE_DATA_API_KEY: storeString(store.get('youtubeDataApiKey', ''), ''),
  }
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
    // In production, prefer PyInstaller API binary (scripts/build-python.py); fall back to bundled interpreter layout.
    if (app.isPackaged) {
      const base = path.join(process.resourcesPath, 'python')
      const winApi = path.join(base, 'youtube-scrape-api.exe')
      const posixApi = path.join(base, 'youtube-scrape-api')
      if (process.platform === 'win32' && fs.existsSync(winApi)) {
        return winApi
      }
      if (process.platform !== 'win32' && fs.existsSync(posixApi)) {
        return posixApi
      }
      if (process.platform === 'win32') {
        return path.join(base, 'python.exe')
      }
      return path.join(base, 'bin', 'python')
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

  async start(
    allowedOutputRoots?: string[],
    scrapeEnvExtras: PythonSpawnEnvExtras = {}
  ): Promise<{ success: boolean; error?: string }> {
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

      const isBundledApiBinary =
        app.isPackaged &&
        (this.config.pythonPath.endsWith('youtube-scrape-api.exe') ||
          this.config.pythonPath.endsWith('youtube-scrape-api'))

      const args = isBundledApiBinary
        ? ['--host', this.config.host, '--port', port.toString()]
        : [
            '-u',
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
        NODE_ENV: this.isDev ? 'development' : 'production',
        ...scrapeEnvExtras,
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
