import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  FolderOpen,
  Moon,
  Sun,
  Monitor,
  Save,
  RotateCcw,
  Check,
  AlertCircle,
  FileCode,
  HardDrive,
  Download,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import {
  useAppStore,
  UI_FONT_SIZE_MIN,
  UI_FONT_SIZE_MAX,
  UI_FONT_SIZE_DEFAULT,
  DOWNLOAD_MAX_CONCURRENT_MIN,
  DOWNLOAD_MAX_CONCURRENT_MAX,
  DOWNLOAD_MAX_CONCURRENT_DEFAULT,
  FFMPEG_THREADS_MAX,
} from '../stores/appStore'
import toast from 'react-hot-toast'
import { joinServerUrl } from '../utils/joinServerUrl'
import {
  ANALYTICS_LLM_PROVIDER_OPTIONS,
  ANALYTICS_LLM_STORE_DEFAULTS,
  type AnalyticsLlmProviderId,
} from '../config/analyticsLlmSettings'
import { persistAnalyticsLlmUiToStore, readGuiAnalyticsLlmOverlay } from '../utils/guiAnalyticsLlmOverlay'

const SettingsView: React.FC = () => {
  const {
    isDarkMode,
    setDarkMode,
    outputDirectory,
    setOutputDirectory,
    uiFontSizePercent,
    setUiFontSizePercent,
    downloadMaxConcurrentJobs,
    ffmpegThreads,
    setDownloadMaxConcurrentJobs,
    setFfmpegThreads,
    serverUrl,
  } = useAppStore()
  const [restartingPy, setRestartingPy] = useState(false)
  const [pythonPath, setPythonPath] = useState('')
  const [isCheckingPython, setIsCheckingPython] = useState(false)
  const [pythonStatus, setPythonStatus] = useState<'ok' | 'error' | null>(null)
  const [appVersion, setAppVersion] = useState('')
  const [platform, setPlatform] = useState('')
  const [nodeArch, setNodeArch] = useState('—')
  const [nodeVersion, setNodeVersion] = useState('—')
  const [electronVersion, setElectronVersion] = useState('—')

  const [llmProvider, setLlmProvider] = useState<AnalyticsLlmProviderId>(
    ANALYTICS_LLM_STORE_DEFAULTS.analyticsLlmProvider
  )
  const [analyticsLlmEnabled, setAnalyticsLlmEnabled] = useState(true)
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState(ANALYTICS_LLM_STORE_DEFAULTS.ollamaBaseUrl)
  const [ollamaModel, setOllamaModel] = useState(ANALYTICS_LLM_STORE_DEFAULTS.ollamaModel)
  const [openaiCompatibleBaseUrl, setOpenaiCompatibleBaseUrl] = useState(
    ANALYTICS_LLM_STORE_DEFAULTS.openaiCompatibleBaseUrl
  )
  const [openaiCompatibleApiKey, setOpenaiCompatibleApiKey] = useState(
    ANALYTICS_LLM_STORE_DEFAULTS.openaiCompatibleApiKey
  )
  const [openaiCompatibleModel, setOpenaiCompatibleModel] = useState(
    ANALYTICS_LLM_STORE_DEFAULTS.openaiCompatibleModel
  )
  const [anthropicBaseUrl, setAnthropicBaseUrl] = useState(ANALYTICS_LLM_STORE_DEFAULTS.anthropicBaseUrl)
  const [anthropicApiKey, setAnthropicApiKey] = useState(ANALYTICS_LLM_STORE_DEFAULTS.anthropicApiKey)
  const [anthropicModel, setAnthropicModel] = useState(ANALYTICS_LLM_STORE_DEFAULTS.anthropicModel)
  const [googleGeminiApiKey, setGoogleGeminiApiKey] = useState(ANALYTICS_LLM_STORE_DEFAULTS.googleGeminiApiKey)
  const [googleGeminiModel, setGoogleGeminiModel] = useState(ANALYTICS_LLM_STORE_DEFAULTS.googleGeminiModel)
  const [llmProbeBusy, setLlmProbeBusy] = useState(false)
  const [llmSaving, setLlmSaving] = useState(false)
  const [llmStoreHydrated, setLlmStoreHydrated] = useState(false)

  useEffect(() => {
    if (!window.electronAPI) {
      return
    }
    void window.electronAPI.getAppVersion().then(setAppVersion).catch(() => setAppVersion(''))
    void window.electronAPI.getPlatform().then(setPlatform).catch(() => setPlatform(''))
    void window.electronAPI
      .storeGet('pythonPath')
      .then((path) => {
        if (path) {
          setPythonPath(path as string)
        }
      })
      .catch(() => {
        // ignore
      })
    void window.electronAPI
      .getAppRuntime()
      .then((r) => {
        setNodeArch(r.arch)
        setNodeVersion(r.node)
        setElectronVersion(r.electron)
      })
      .catch(() => {
        // ignore
      })
  }, [])

  useEffect(() => {
    if (!window.electronAPI) {
      return
    }
    const d = ANALYTICS_LLM_STORE_DEFAULTS
    const asProvider = (raw: unknown): AnalyticsLlmProviderId => {
      const s = typeof raw === 'string' ? raw : ''
      return ANALYTICS_LLM_PROVIDER_OPTIONS.some((x) => x.id === s)
        ? (s as AnalyticsLlmProviderId)
        : d.analyticsLlmProvider
    }
    void Promise.all([
      window.electronAPI.storeGet('analyticsLlmProvider'),
      window.electronAPI.storeGet('analyticsOllamaEnabled'),
      window.electronAPI.storeGet('ollamaBaseUrl'),
      window.electronAPI.storeGet('ollamaModel'),
      window.electronAPI.storeGet('openaiCompatibleBaseUrl'),
      window.electronAPI.storeGet('openaiCompatibleApiKey'),
      window.electronAPI.storeGet('openaiCompatibleModel'),
      window.electronAPI.storeGet('anthropicBaseUrl'),
      window.electronAPI.storeGet('anthropicApiKey'),
      window.electronAPI.storeGet('anthropicModel'),
      window.electronAPI.storeGet('googleGeminiApiKey'),
      window.electronAPI.storeGet('googleGeminiModel'),
    ]).then(
      ([
        p,
        en,
        obu,
        om,
        ocbu,
        ocak,
        ocm,
        abu,
        aak,
        am,
        ggk,
        ggm,
      ]) => {
        setLlmProvider(asProvider(p))
        if (en === false) {
          setAnalyticsLlmEnabled(false)
        } else {
          setAnalyticsLlmEnabled(true)
        }
        if (typeof obu === 'string' && obu.trim()) {
          setOllamaBaseUrl(obu.trim())
        }
        if (typeof om === 'string' && om.trim()) {
          setOllamaModel(om.trim())
        }
        if (typeof ocbu === 'string' && ocbu.trim()) {
          setOpenaiCompatibleBaseUrl(ocbu.trim())
        }
        if (typeof ocak === 'string') {
          setOpenaiCompatibleApiKey(ocak)
        }
        if (typeof ocm === 'string' && ocm.trim()) {
          setOpenaiCompatibleModel(ocm.trim())
        }
        if (typeof abu === 'string' && abu.trim()) {
          setAnthropicBaseUrl(abu.trim())
        }
        if (typeof aak === 'string') {
          setAnthropicApiKey(aak)
        }
        if (typeof am === 'string' && am.trim()) {
          setAnthropicModel(am.trim())
        }
        if (typeof ggk === 'string') {
          setGoogleGeminiApiKey(ggk)
        }
        if (typeof ggm === 'string' && ggm.trim()) {
          setGoogleGeminiModel(ggm.trim())
        }
      }
    ).finally(() => {
      setLlmStoreHydrated(true)
    })
  }, [])

  useEffect(() => {
    if (!window.electronAPI || !llmStoreHydrated) {
      return undefined
    }
    const id = window.setTimeout(() => {
      void persistAnalyticsLlmUiToStore({
        llmProvider,
        analyticsLlmEnabled,
        ollamaBaseUrl,
        ollamaModel,
        openaiCompatibleBaseUrl,
        openaiCompatibleApiKey,
        openaiCompatibleModel,
        anthropicBaseUrl,
        anthropicApiKey,
        anthropicModel,
        googleGeminiApiKey,
        googleGeminiModel,
      }).catch(() => {
        /* debounced autosave failed — user can retry with Save LLM settings */
      })
    }, 700)
    return () => window.clearTimeout(id)
  }, [
    analyticsLlmEnabled,
    anthropicApiKey,
    anthropicBaseUrl,
    anthropicModel,
    googleGeminiApiKey,
    googleGeminiModel,
    llmProvider,
    ollamaBaseUrl,
    ollamaModel,
    openaiCompatibleApiKey,
    openaiCompatibleBaseUrl,
    openaiCompatibleModel,
    llmStoreHydrated,
  ])

  const handleSelectOutputDir = async () => {
    const result = await window.electronAPI.selectDirectory()
    if (!result.canceled && result.filePaths.length > 0) {
      setOutputDirectory(result.filePaths[0])
      toast.success('Output directory updated')
    }
  }

  const handleSavePythonPath = async () => {
    await window.electronAPI.storeSet('pythonPath', pythonPath)
    toast.success('Python path saved')
  }

  const handleCheckPython = async () => {
    setIsCheckingPython(true)
    // In a real implementation, we'd verify the Python path
    setTimeout(() => {
      setPythonStatus('ok')
      setIsCheckingPython(false)
    }, 1000)
  }

  const handleSaveLlmSettings = async () => {
    if (!window.electronAPI) {
      return
    }
    setLlmSaving(true)
    try {
      await persistAnalyticsLlmUiToStore({
        llmProvider,
        analyticsLlmEnabled,
        ollamaBaseUrl,
        ollamaModel,
        openaiCompatibleBaseUrl,
        openaiCompatibleApiKey,
        openaiCompatibleModel,
        anthropicBaseUrl,
        anthropicApiKey,
        anthropicModel,
        googleGeminiApiKey,
        googleGeminiModel,
      })
      toast.success(
        'LLM settings saved. Analytics uses them immediately via API overlay; restart the API only if non-analytics CLI/scrape picks should match.'
      )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to save LLM settings')
    } finally {
      setLlmSaving(false)
    }
  }

  const handleTestLlmConnection = async () => {
    if (!window.electronAPI) {
      return
    }
    if (!serverUrl) {
      toast.error('Python API server is not running')
      void useAppStore.getState().checkServerStatus()
      return
    }
    setLlmProbeBusy(true)
    try {
      const guiOverlay = await readGuiAnalyticsLlmOverlay()
      const res = await fetch(joinServerUrl(serverUrl, '/analytics/llm-probe'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gui_llm_overlay: guiOverlay ?? {} }),
      })
      const text = await res.text()
      let body: {
        detail?: unknown
        ok?: boolean
        message?: string
        models_sample?: string[]
        provider?: string
      } = {}
      try {
        body = JSON.parse(text) as typeof body
      } catch {
        body = {}
      }
      if (!res.ok) {
        const det =
          typeof body.detail === 'string'
            ? body.detail
            : Array.isArray(body.detail)
              ? JSON.stringify(body.detail)
              : text.slice(0, 400)
        toast.error(det || `HTTP ${res.status}`)
        return
      }
      const msg =
        typeof body.message === 'string' && body.message
          ? body.message
          : body.ok === false
            ? 'Unreachable'
            : 'OK'
      if (body.ok) {
        const extra =
          Array.isArray(body.models_sample) && body.models_sample.length > 0
            ? ` Models: ${body.models_sample.slice(0, 5).join(', ')}${body.models_sample.length > 5 ? '…' : ''}.`
            : ''
        toast.success(`${msg}.${extra}`)
      } else {
        toast.error(msg)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Probe request failed')
    } finally {
      setLlmProbeBusy(false)
    }
  }

  const handleResetSettings = async () => {
    if (confirm('Are you sure you want to reset all settings to defaults?')) {
      await window.electronAPI.storeSet('outputDirectory', '')
      await window.electronAPI.storeSet('pythonPath', '')
      await window.electronAPI.storeSet('uiFontSizePercent', UI_FONT_SIZE_DEFAULT)
      await window.electronAPI.storeSet('downloadMaxConcurrentJobs', DOWNLOAD_MAX_CONCURRENT_DEFAULT)
      await window.electronAPI.storeSet('ffmpegThreads', 0)
      const d = ANALYTICS_LLM_STORE_DEFAULTS
      await window.electronAPI.storeSet('analyticsLlmProvider', d.analyticsLlmProvider)
      await window.electronAPI.storeSet('analyticsOllamaEnabled', d.analyticsOllamaEnabled)
      await window.electronAPI.storeSet('ollamaBaseUrl', d.ollamaBaseUrl)
      await window.electronAPI.storeSet('ollamaModel', d.ollamaModel)
      await window.electronAPI.storeSet('openaiCompatibleBaseUrl', d.openaiCompatibleBaseUrl)
      await window.electronAPI.storeSet('openaiCompatibleApiKey', d.openaiCompatibleApiKey)
      await window.electronAPI.storeSet('openaiCompatibleModel', d.openaiCompatibleModel)
      await window.electronAPI.storeSet('anthropicBaseUrl', d.anthropicBaseUrl)
      await window.electronAPI.storeSet('anthropicApiKey', d.anthropicApiKey)
      await window.electronAPI.storeSet('anthropicModel', d.anthropicModel)
      await window.electronAPI.storeSet('googleGeminiApiKey', d.googleGeminiApiKey)
      await window.electronAPI.storeSet('googleGeminiModel', d.googleGeminiModel)
      setOutputDirectory('')
      setPythonPath('')
      setUiFontSizePercent(UI_FONT_SIZE_DEFAULT)
      setDownloadMaxConcurrentJobs(DOWNLOAD_MAX_CONCURRENT_DEFAULT)
      setFfmpegThreads(0)
      setLlmProvider(d.analyticsLlmProvider)
      setAnalyticsLlmEnabled(d.analyticsOllamaEnabled)
      setOllamaBaseUrl(d.ollamaBaseUrl)
      setOllamaModel(d.ollamaModel)
      setOpenaiCompatibleBaseUrl(d.openaiCompatibleBaseUrl)
      setOpenaiCompatibleApiKey(d.openaiCompatibleApiKey)
      setOpenaiCompatibleModel(d.openaiCompatibleModel)
      setAnthropicBaseUrl(d.anthropicBaseUrl)
      setAnthropicApiKey(d.anthropicApiKey)
      setAnthropicModel(d.anthropicModel)
      setGoogleGeminiApiKey(d.googleGeminiApiKey)
      setGoogleGeminiModel(d.googleGeminiModel)
      toast.success('Settings reset to defaults')
    }
  }

  const handleRestartApi = async () => {
    if (!window.electronAPI?.restartPythonServer) {
      toast.error('Restart is not available in this environment')
      return
    }
    setRestartingPy(true)
    try {
      const r = await window.electronAPI.restartPythonServer()
      if (!r.success) {
        toast.error(r.error ?? 'Failed to restart API server')
      } else {
        toast.success('Python API restarted with your download settings')
        void useAppStore.getState().checkServerStatus()
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to restart API')
    } finally {
      setRestartingPy(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="mb-6">
        <h2 className="text-2xl font-display font-bold text-white">Settings</h2>
        <p className="text-space-400">Configure your scraping preferences</p>
      </div>

      {/* Appearance */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card p-6"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-neon-purple/10 flex items-center justify-center">
            <Monitor className="w-5 h-5 text-neon-purple" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Appearance</h3>
            <p className="text-sm text-space-400">Customize the visual theme and text size</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={() => setDarkMode(false)}
            className={`
              flex-1 flex items-center gap-3 p-4 rounded-xl border transition-all
              ${!isDarkMode
                ? 'bg-neon-blue/10 border-neon-blue/40 text-white'
                : 'bg-white/5 border-glass-border text-space-300 hover:bg-white/[0.07]'
              }
            `}
          >
            <Sun className={`w-5 h-5 ${!isDarkMode ? 'text-neon-blue' : ''}`} />
            <span>Light Mode</span>
          </button>
          <button
            onClick={() => setDarkMode(true)}
            className={`
              flex-1 flex items-center gap-3 p-4 rounded-xl border transition-all
              ${isDarkMode
                ? 'bg-neon-blue/10 border-neon-blue/40 text-white'
                : 'bg-white/5 border-glass-border text-space-300 hover:bg-white/[0.07]'
              }
            `}
          >
            <Moon className={`w-5 h-5 ${isDarkMode ? 'text-neon-blue' : ''}`} />
            <span>Dark Mode</span>
          </button>
        </div>

        <div className="mt-6 pt-6 border-t border-glass-border/80">
          <p className="text-sm font-medium text-white mb-1">Text size</p>
          <p className="text-xs text-space-400 mb-4">Scales the interface. Uses rem so most UI updates together.</p>
          <div className="flex items-center gap-3">
            <span className="text-xs text-space-500 w-8 shrink-0">{UI_FONT_SIZE_MIN}%</span>
            <input
              type="range"
              min={UI_FONT_SIZE_MIN}
              max={UI_FONT_SIZE_MAX}
              step={5}
              value={uiFontSizePercent}
              onChange={(e) => setUiFontSizePercent(Number(e.target.value))}
              className="flex-1 h-2 rounded-full accent-cyan-500"
              aria-label="Interface text size"
            />
            <span className="text-xs text-space-500 w-8 shrink-0 text-right">{UI_FONT_SIZE_MAX}%</span>
          </div>
          <p className="text-center text-sm text-neon-cyan font-medium tabular-nums mt-2">{uiFontSizePercent}%</p>
          <div className="flex flex-wrap justify-center gap-2 mt-3">
            {(
              [
                { label: 'Small', v: 90 },
                { label: 'Default', v: 100 },
                { label: 'Large', v: 115 },
                { label: 'Extra', v: 130 },
              ] as const
            ).map((p) => (
              <button
                key={p.v}
                type="button"
                onClick={() => setUiFontSizePercent(p.v)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                  uiFontSizePercent === p.v
                    ? 'border-neon-blue/50 bg-neon-blue/10 text-white'
                    : 'border-glass-border text-space-300 hover:bg-white/5'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </motion.div>

      {/* Output Directory */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass-card p-6"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-neon-green/10 flex items-center justify-center">
            <FolderOpen className="w-5 h-5 text-neon-green" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Output Directory</h3>
            <p className="text-sm text-space-400">Where scraped data will be saved</p>
          </div>
        </div>

        <div className="flex gap-3">
          <div className="flex-1 futuristic-input flex items-center px-4 py-3">
            <HardDrive className="w-5 h-5 text-space-400 mr-3" />
            <span className="text-space-300 truncate">
              {outputDirectory || 'Default (./output)'}
            </span>
          </div>
          <button
            onClick={handleSelectOutputDir}
            className="futuristic-btn flex items-center gap-2 px-6"
          >
            <FolderOpen className="w-4 h-4" />
            Browse
          </button>
        </div>
      </motion.div>

      {/* Download & scrape pipeline */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="glass-card p-6"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
            <Download className="w-5 h-5 text-amber-300" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Download & scraping</h3>
            <p className="text-sm text-space-400">
              Limit how much runs at once (heavy browser work). FFmpeg threads affect audio transcoding/remux only.
            </p>
          </div>
        </div>

        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-space-200 mb-1">
              Active scrape jobs at once
            </label>
            <p className="text-xs text-space-500 mb-2">
              How many videos can scrape in parallel on the Python API (each opens browser sessions).
            </p>
            <input
              type="number"
              min={DOWNLOAD_MAX_CONCURRENT_MIN}
              max={DOWNLOAD_MAX_CONCURRENT_MAX}
              value={downloadMaxConcurrentJobs}
              onChange={(e) => setDownloadMaxConcurrentJobs(Number(e.target.value))}
              className="futuristic-input w-28 px-3 py-2"
            />
            <span className="ml-2 text-xs text-space-500 tabular-nums">
              ({DOWNLOAD_MAX_CONCURRENT_MIN}–{DOWNLOAD_MAX_CONCURRENT_MAX})
            </span>
          </div>
          <div>
            <label className="block text-sm font-medium text-space-200 mb-1">FFmpeg threads</label>
            <p className="text-xs text-space-500 mb-2">
              Passed as <code className="text-space-400">-threads N</code> for MP3 encode/remux helpers.{' '}
              <span className="text-space-600">Use 0 for FFmpeg default/auto.</span>
            </p>
            <input
              type="number"
              min={0}
              max={FFMPEG_THREADS_MAX}
              value={ffmpegThreads}
              onChange={(e) => setFfmpegThreads(Number(e.target.value))}
              className="futuristic-input w-28 px-3 py-2"
            />
            <span className="ml-2 text-xs text-space-500 tabular-nums">
              (0–{FFMPEG_THREADS_MAX})
            </span>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-glass-border/80 pt-5">
          <button
            type="button"
            onClick={() => void handleRestartApi()}
            disabled={restartingPy}
            className="futuristic-btn flex items-center gap-2 px-5"
          >
            {restartingPy ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-neon-blue/40 border-t-neon-blue" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Restart API server
          </button>
          <p className="text-xs text-space-500 max-w-xl">
            The Python process reads these values when it starts. After changing sliders, restart once so concurrency
            and FFmpeg settings apply (running jobs should finish or be cancelled first if needed).
          </p>
        </div>
      </motion.div>

      {/* Analytics LLM */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.18 }}
        className="glass-card p-6"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-violet-500/10 flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-violet-300" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Analytics LLM</h3>
            <p className="text-sm text-space-400">
              Provider for Analytics comment summaries. Preferences auto-save shortly after you edit. Each Analytics
              request sends this snapshot so remote Ollama works without restarting the API; restart remains useful so
              the Python process env matches for other tooling.
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-space-200 mb-1">Provider</label>
            <select
              value={llmProvider}
              onChange={(e) => setLlmProvider(e.target.value as AnalyticsLlmProviderId)}
              className="futuristic-input w-full max-w-md px-3 py-2"
              aria-label="LLM provider"
            >
              {ANALYTICS_LLM_PROVIDER_OPTIONS.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {llmProvider === 'ollama' && (
            <div className="space-y-3 border border-glass-border/60 rounded-xl p-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={analyticsLlmEnabled}
                  onChange={(e) => setAnalyticsLlmEnabled(e.target.checked)}
                  className="rounded border-glass-border"
                />
                <span className="text-sm text-space-200">Enable LLM calls for analytics</span>
              </label>
              <div>
                <label className="block text-xs text-space-400 mb-1">Ollama base URL</label>
                <input
                  type="text"
                  value={ollamaBaseUrl}
                  onChange={(e) => setOllamaBaseUrl(e.target.value)}
                  placeholder="http://127.0.0.1:11434"
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-space-400 mb-1">Model</label>
                <input
                  type="text"
                  value={ollamaModel}
                  onChange={(e) => setOllamaModel(e.target.value)}
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
            </div>
          )}

          {llmProvider === 'openai_compatible' && (
            <div className="space-y-3 border border-glass-border/60 rounded-xl p-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={analyticsLlmEnabled}
                  onChange={(e) => setAnalyticsLlmEnabled(e.target.checked)}
                  className="rounded border-glass-border"
                />
                <span className="text-sm text-space-200">Enable LLM calls for analytics</span>
              </label>
              <div>
                <label className="block text-xs text-space-400 mb-1">Base URL</label>
                <input
                  type="text"
                  value={openaiCompatibleBaseUrl}
                  onChange={(e) => setOpenaiCompatibleBaseUrl(e.target.value)}
                  placeholder="https://api.openai.com/v1"
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-space-400 mb-1">API key (optional)</label>
                <input
                  type="password"
                  value={openaiCompatibleApiKey}
                  onChange={(e) => setOpenaiCompatibleApiKey(e.target.value)}
                  autoComplete="off"
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-space-400 mb-1">Model id</label>
                <input
                  type="text"
                  value={openaiCompatibleModel}
                  onChange={(e) => setOpenaiCompatibleModel(e.target.value)}
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
            </div>
          )}

          {llmProvider === 'anthropic' && (
            <div className="space-y-3 border border-glass-border/60 rounded-xl p-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={analyticsLlmEnabled}
                  onChange={(e) => setAnalyticsLlmEnabled(e.target.checked)}
                  className="rounded border-glass-border"
                />
                <span className="text-sm text-space-200">Enable LLM calls for analytics</span>
              </label>
              <div>
                <label className="block text-xs text-space-400 mb-1">API base URL</label>
                <input
                  type="text"
                  value={anthropicBaseUrl}
                  onChange={(e) => setAnthropicBaseUrl(e.target.value)}
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-space-400 mb-1">API key</label>
                <input
                  type="password"
                  value={anthropicApiKey}
                  onChange={(e) => setAnthropicApiKey(e.target.value)}
                  autoComplete="off"
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-space-400 mb-1">Model id</label>
                <input
                  type="text"
                  value={anthropicModel}
                  onChange={(e) => setAnthropicModel(e.target.value)}
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
            </div>
          )}

          {llmProvider === 'google_gemini' && (
            <div className="space-y-3 border border-glass-border/60 rounded-xl p-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={analyticsLlmEnabled}
                  onChange={(e) => setAnalyticsLlmEnabled(e.target.checked)}
                  className="rounded border-glass-border"
                />
                <span className="text-sm text-space-200">Enable LLM calls for analytics</span>
              </label>
              <div>
                <label className="block text-xs text-space-400 mb-1">API key</label>
                <input
                  type="password"
                  value={googleGeminiApiKey}
                  onChange={(e) => setGoogleGeminiApiKey(e.target.value)}
                  autoComplete="off"
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-space-400 mb-1">Model id</label>
                <input
                  type="text"
                  value={googleGeminiModel}
                  onChange={(e) => setGoogleGeminiModel(e.target.value)}
                  className="futuristic-input w-full px-3 py-2 font-mono text-sm"
                />
              </div>
            </div>
          )}

          <p className="text-xs text-space-500">
            API keys are stored in the desktop app preferences (not encrypted). Use `.env` for stricter setups.
          </p>

          <div className="flex flex-wrap gap-3 pt-1">
            <button
              type="button"
              onClick={() => void handleSaveLlmSettings()}
              disabled={llmSaving}
              className="futuristic-btn futuristic-btn-primary flex items-center gap-2 px-5"
            >
              {llmSaving ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Save LLM settings
            </button>
            <button
              type="button"
              onClick={() => void handleTestLlmConnection()}
              disabled={llmProbeBusy}
              className="futuristic-btn flex items-center gap-2 px-5"
            >
              {llmProbeBusy ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-neon-blue/40 border-t-neon-blue" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Test connection
            </button>
          </div>
        </div>
      </motion.div>

      {/* Python Configuration */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="glass-card p-6"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-neon-blue/10 flex items-center justify-center">
            <FileCode className="w-5 h-5 text-neon-blue" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Python Configuration</h3>
            <p className="text-sm text-space-400">Path to Python executable (optional)</p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <input
                type="text"
                value={pythonPath}
                onChange={(e) => setPythonPath(e.target.value)}
                placeholder="Auto-detected"
                className="futuristic-input w-full px-4 py-3"
              />
              {pythonStatus === 'ok' && (
                <Check className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-neon-green" />
              )}
            </div>
            <button
              onClick={handleCheckPython}
              disabled={isCheckingPython || !pythonPath}
              className="futuristic-btn flex items-center gap-2 px-4"
            >
              {isCheckingPython ? (
                <div className="w-4 h-4 border-2 border-neon-blue/30 border-t-neon-blue rounded-full animate-spin" />
              ) : (
                <Check className="w-4 h-4" />
              )}
              Test
            </button>
            <button
              onClick={handleSavePythonPath}
              disabled={!pythonPath}
              className="futuristic-btn futuristic-btn-primary flex items-center gap-2 px-4"
            >
              <Save className="w-4 h-4" />
              Save
            </button>
          </div>

          {pythonStatus === 'error' && (
            <p className="text-sm text-rose-400 flex items-center gap-1">
              <AlertCircle className="w-4 h-4" />
              Python not found at this path
            </p>
          )}
        </div>
      </motion.div>

      {/* Application Info */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="glass-card p-6"
      >
        <h3 className="font-semibold text-white mb-4">Application Info</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-space-400">Version</p>
            <p className="text-white">{appVersion}</p>
          </div>
          <div>
            <p className="text-space-400">Platform</p>
            <p className="text-white capitalize">{platform}</p>
          </div>
          <div>
            <p className="text-space-400">Architecture</p>
            <p className="text-white">{nodeArch}</p>
          </div>
          <div>
            <p className="text-space-400">Node / Electron</p>
            <p className="text-white">
              Node {nodeVersion}
              {electronVersion !== '—' && (
                <span className="text-space-400"> · Electron {electronVersion}</span>
              )}
            </p>
          </div>
        </div>
      </motion.div>

      {/* Keyboard Shortcuts */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35 }}
        className="glass-card p-6"
      >
        <h3 className="font-semibold text-white mb-4">Keyboard Shortcuts</h3>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <ShortcutItem shortcut="⌘N" description="New Scrape" />
          <ShortcutItem shortcut="⌘J" description="Open Jobs" />
          <ShortcutItem shortcut="⌘R" description="Open Results" />
          <ShortcutItem shortcut="⌘," description="Open Settings" />
          <ShortcutItem shortcut="⌘D" description="Open Debug" />
          <ShortcutItem shortcut="⌘⇧L" description="Toggle Theme" />
          <ShortcutItem shortcut="⌘F" description="Search" />
          <ShortcutItem shortcut="Esc" description="Go Back" />
        </div>
        <p className="text-xs text-space-400 mt-3">
          On Windows/Linux, use Ctrl instead of ⌘
        </p>
      </motion.div>

      {/* Reset */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="flex justify-end"
      >
        <button
          onClick={handleResetSettings}
          className="flex items-center gap-2 text-rose-400 hover:text-rose-300 transition-colors"
        >
          <RotateCcw className="w-4 h-4" />
          Reset all settings to defaults
        </button>
      </motion.div>
    </div>
  )
}

const ShortcutItem: React.FC<{ shortcut: string; description: string }> = ({
  shortcut,
  description,
}) => (
  <div className="flex items-center justify-between py-2 border-b border-glass-border last:border-0">
    <span className="text-space-300">{description}</span>
    <kbd className="px-2 py-1 rounded bg-space-700 text-neon-cyan font-mono text-xs">
      {shortcut}
    </kbd>
  </div>
)

export default SettingsView
