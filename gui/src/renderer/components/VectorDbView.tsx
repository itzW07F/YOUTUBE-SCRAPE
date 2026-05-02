import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileText,
  Globe,
  Loader2,
  Play,
  RefreshCw,
  Search,
  XCircle,
  Zap,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useScrapeStore } from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'
import { useVideoResults } from '../hooks/useVideoResults'
import {
  useVectorDbStore,
  fetchRagStatus,
  startRagBuild,
  fetchGlobalRagStatus,
  fetchJobStatus,
} from '../stores/vectorDbStore'
import { joinServerUrl } from '../utils/joinServerUrl'

interface CollapsibleSectionProps {
  title: React.ReactNode
  subtitle?: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
  headerRight?: React.ReactNode
  compact?: boolean
}

const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
  title,
  subtitle,
  defaultOpen = true,
  children,
  headerRight,
  compact = false,
}) => {
  const [open, setOpen] = useState(defaultOpen)
  const headerPad = compact ? 'px-3 py-2' : 'px-5 py-3'
  const titleCls = compact ? 'block text-sm font-semibold text-white' : 'block text-lg font-semibold text-white'

  return (
    <div className="glass-card overflow-hidden">
      <div className={`flex items-start gap-2 border-b border-white/10 ${headerPad} ${headerRight ? 'flex-wrap' : ''}`}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-start gap-2 rounded-md px-2 py-1 text-left -mx-2 hover:bg-white/5"
          aria-expanded={open}
        >
          <span className={`mt-0.5 shrink-0 text-space-400 ${compact ? 'mt-px' : ''}`}>
            {open ? <span className="text-xs">▼</span> : <span className="text-xs">▶</span>}
          </span>
          <span className="min-w-0 flex-1">
            <span className={titleCls}>{title}</span>
            {subtitle ? <span className="mt-0.5 block text-xs text-space-500">{subtitle}</span> : null}
          </span>
        </button>
        {headerRight ? <div className="flex shrink-0 flex-wrap items-center gap-2">{headerRight}</div> : null}
      </div>
      {open ? <div className="p-5">{children}</div> : null}
    </div>
  )
}

/** WebSocket payloads for `/ws/progress` (normalized + legacy `data` snapshots). */
type RagWsFrame = {
  type?: string
  status?: unknown
  details?: unknown
  progress?: unknown
  data?: unknown
}

const VectorDbView: React.FC = () => {
  // Store state
  const jobs = useScrapeStore((s) => s.jobs)
  const galleryDiskRevisionBump = useScrapeStore((s) => s.galleryDiskRevisionBump)
  const results = useVideoResults(jobs, galleryDiskRevisionBump)
  const serverUrl = useAppStore((s) => s.serverUrl)
  const isServerRunning = useAppStore((s) => s.isServerRunning)

  // Vector DB store
  const {
    selectedOutputDir,
    setSelectedOutputDir,
    ragStatus,
    setRagStatus,
    isLoadingStatus,
    setIsLoadingStatus,
    statusError,
    setStatusError,
    ragBuildPhase,
    setRagBuildPhase,
    ragBuildJobId,
    setRagBuildJobId,
    ragBuildProgress,
    setRagBuildProgress,
    ragBuildError,
    setRagBuildError,
    lastBuildResult,
    setLastBuildResult,
    resetBuildState,
    viewMode,
    setViewMode,
    globalStatus,
    setGlobalStatus,
    isLoadingGlobal,
    setIsLoadingGlobal,
    globalError,
    setGlobalError,
  } = useVectorDbStore()

  // Local state
  const [isBuilding, setIsBuilding] = useState(false)
  const [globalFilter, setGlobalFilter] = useState('')
  const ragClosePollCleanupRef = React.useRef<number | null>(null)
  const ragTerminalHandledRef = React.useRef(false)

  // Sort results alphabetically
  const sortedResults = useMemo(
    () => [...results].sort((a, b) => a.title.localeCompare(b.title)),
    [results]
  )

  // Fetch status when selection changes
  const loadStatus = useCallback(async () => {
    if (!serverUrl || !selectedOutputDir || !isServerRunning) return
    setIsLoadingStatus(true)
    setStatusError(null)
    try {
      const status = await fetchRagStatus(serverUrl, selectedOutputDir)
      setRagStatus(status)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setStatusError(msg)
      toast.error('Failed to load RAG status')
    } finally {
      setIsLoadingStatus(false)
    }
  }, [serverUrl, selectedOutputDir, isServerRunning, setRagStatus, setStatusError, setIsLoadingStatus])

  const applyTerminalRagJobStatus = useCallback(
    (terminal: string, details: Record<string, unknown> | undefined, jobFallback?: Record<string, unknown>) => {
      if (ragTerminalHandledRef.current) return
      if (terminal !== 'completed' && terminal !== 'failed') return
      ragTerminalHandledRef.current = true

      if (terminal === 'completed') {
        setRagBuildPhase('completed')
        setRagBuildProgress(100)
        setRagBuildError(null)

        let chunkCount =
          typeof details?.chunk_count === 'number'
            ? details.chunk_count
            : typeof details?.chunkCount === 'number'
              ? (details.chunkCount as number)
              : 0

        if (!chunkCount && jobFallback) {
          const res = jobFallback.result
          if (typeof res === 'object' && res !== null && 'chunk_count' in res) {
            const cc = (res as Record<string, unknown>).chunk_count
            if (typeof cc === 'number') chunkCount = cc
          }
        }

        setLastBuildResult({ success: true, chunkCount })
        toast.success(typeof details?.message === 'string' ? details.message : 'RAG index built successfully')
        setTimeout(() => void loadStatus(), 400)
        return
      }

      setRagBuildPhase('failed')
      setRagBuildProgress(100)
      let err =
        typeof details?.error === 'string'
          ? details.error
          : typeof details?.message === 'string'
            ? (details.message as string)
            : null
      if (!err && jobFallback && typeof jobFallback.error === 'string') err = jobFallback.error
      if (!err) err = 'RAG build failed'
      setRagBuildError(err)
      setLastBuildResult({ success: false, chunkCount: 0 })
      toast.error(err)
    },
    [loadStatus, setLastBuildResult, setRagBuildPhase, setRagBuildProgress, setRagBuildError]
  )

  const parseWsStatusPayload = useCallback((raw: RagWsFrame) => {
    if (raw.type !== 'status') return { terminal: undefined as string | undefined, details: undefined as Record<string, unknown> | undefined }
    if (typeof raw.status === 'string') {
      return {
        terminal: raw.status,
        details:
          typeof raw.details === 'object' && raw.details !== null ? (raw.details as Record<string, unknown>) : {},
      }
    }
    const legacySnap = raw.data
    if (typeof legacySnap === 'object' && legacySnap !== null) {
      const j = legacySnap as Record<string, unknown>
      if (typeof j.status === 'string') {
        const d: Record<string, unknown> = {}
        if (typeof j.error === 'string') d.error = j.error
        const res = j.result
        if (typeof res === 'object' && res !== null && 'chunk_count' in res) {
          const cc = (res as Record<string, unknown>).chunk_count
          if (typeof cc === 'number') d.chunk_count = cc
        }
        return { terminal: j.status, details: d }
      }
    }
    return { terminal: undefined, details: undefined }
  }, [])

  useEffect(() => {
    if (selectedOutputDir && isServerRunning) {
      void loadStatus()
    }
  }, [selectedOutputDir, isServerRunning, loadStatus])

  // Reset build state when component mounts or selected folder changes
  // This prevents "stuck" building state from previous sessions
  useEffect(() => {
    // Only reset if we're not currently in an active build
    if (ragBuildPhase !== 'building') {
      resetBuildState()
    }
  }, [selectedOutputDir, ragBuildPhase, resetBuildState])

  // WebSocket for build progress — do NOT list ragBuildPhase in deps (onopen sets "building",
  // which would rerun this effect, close/reopen the socket, and drop terminal status frames).
  useEffect(() => {
    if (!ragBuildJobId || !serverUrl) return

    const wsUrl = joinServerUrl(serverUrl, `/ws/progress/${ragBuildJobId}`).replace(/^http/, 'ws')
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setRagBuildPhase('building')
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as RagWsFrame
        if (data.type === 'progress' && typeof data.progress === 'number') {
          setRagBuildProgress(Math.min(100, Math.max(0, data.progress)))
        }
        const { terminal, details } = parseWsStatusPayload(data)
        if (terminal) {
          applyTerminalRagJobStatus(terminal, details)
        }
      } catch {
        // ignore malformed frames
      }
    }

    ws.onerror = () => {
      /* Browser/Electron emits spurious WS errors during tab switches; reconcile via REST + polling. */
    }

    ws.onclose = () => {
      if (ragClosePollCleanupRef.current !== null) {
        clearInterval(ragClosePollCleanupRef.current)
      }
      let attempts = 0
      const maxAttempts = 6
      ragClosePollCleanupRef.current = window.setInterval(() => {
        attempts++
        void loadStatus()
        if (attempts >= maxAttempts && ragClosePollCleanupRef.current !== null) {
          clearInterval(ragClosePollCleanupRef.current)
          ragClosePollCleanupRef.current = null
        }
      }, 1000)
    }

    return () => {
      if (ragClosePollCleanupRef.current !== null) {
        clearInterval(ragClosePollCleanupRef.current)
        ragClosePollCleanupRef.current = null
      }
      ws.close()
    }
  }, [
    ragBuildJobId,
    serverUrl,
    setRagBuildPhase,
    setRagBuildProgress,
    parseWsStatusPayload,
    applyTerminalRagJobStatus,
    loadStatus,
  ])

  // Authoritative reconciliation: job store survives WebSocket/tab churn for Vector rebuild jobs.
  useEffect(() => {
    if (!ragBuildJobId || !serverUrl || ragBuildPhase !== 'building') return

    let cancelled = false

    const tick = async () => {
      if (cancelled) return
      try {
        const job = await fetchJobStatus(serverUrl, ragBuildJobId)
        if (!job) return
        const st = job.status
        if (typeof st !== 'string') return
        if (st !== 'completed' && st !== 'failed') return

        const err = typeof job.error === 'string' ? job.error : undefined
        applyTerminalRagJobStatus(st, err ? { error: err } : {}, job as Record<string, unknown>)
      } catch {
        // transient disconnects — next tick retries
      }
    }

    void tick()
    const iv = window.setInterval(() => void tick(), 1400)

    return () => {
      cancelled = true
      clearInterval(iv)
    }
  }, [ragBuildJobId, serverUrl, ragBuildPhase, applyTerminalRagJobStatus])

  // Periodic RAG status refresh during active builds (chunks/manifest drift).
  useEffect(() => {
    if (ragBuildPhase !== 'building') return

    const interval = setInterval(() => {
      void loadStatus()
    }, 4000)

    return () => clearInterval(interval)
  }, [ragBuildPhase, loadStatus])

  // Handle build button click
  const handleBuild = async (forceRefresh = false) => {
    if (!serverUrl || !selectedOutputDir) {
      toast.error('Select a video folder first')
      return
    }

    ragTerminalHandledRef.current = false
    resetBuildState()
    setIsBuilding(true)
    setRagBuildPhase('checking')

    try {
      const response = await startRagBuild(serverUrl, selectedOutputDir, forceRefresh)
      if (response.job_id) {
        setRagBuildJobId(response.job_id)
        toast.success('RAG build started')
      } else {
        // No job ID means already up to date
        setRagBuildPhase('completed')
        toast.success(response.message)
        void loadStatus()
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setRagBuildError(msg)
      setRagBuildPhase('failed')
      toast.error(msg)
    } finally {
      setIsBuilding(false)
    }
  }

  // Load global status
  const loadGlobalStatus = useCallback(async () => {
    if (!serverUrl || !isServerRunning) return
    setIsLoadingGlobal(true)
    setGlobalError(null)
    try {
      const status = await fetchGlobalRagStatus(serverUrl)
      setGlobalStatus(status)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setGlobalError(msg)
      toast.error('Failed to load global RAG status')
    } finally {
      setIsLoadingGlobal(false)
    }
  }, [serverUrl, isServerRunning, setGlobalStatus, setGlobalError, setIsLoadingGlobal])

  useEffect(() => {
    if (viewMode === 'global' && isServerRunning) {
      void loadGlobalStatus()
    }
  }, [viewMode, isServerRunning, loadGlobalStatus])

  // Filter global videos
  const filteredGlobalVideos = useMemo(() => {
    if (!globalStatus) return []
    if (!globalFilter.trim()) return globalStatus.videos
    const filter = globalFilter.toLowerCase()
    return globalStatus.videos.filter(
      (v) =>
        (v.title?.toLowerCase().includes(filter) || false) ||
        (v.video_id?.toLowerCase().includes(filter) || false) ||
        v.output_dir.toLowerCase().includes(filter)
    )
  }, [globalStatus, globalFilter])

  // Source type icons
  const getSourceIcon = (source: string) => {
    if (source.includes('comment')) return <span className="text-neon-purple text-xs">💬</span>
    if (source.includes('transcript')) return <span className="text-neon-green text-xs">📝</span>
    if (source.includes('video')) return <span className="text-neon-blue text-xs">🎬</span>
    if (source.includes('thumbnail')) return <span className="text-amber-400 text-xs">🖼️</span>
    if (source.includes('history')) return <span className="text-space-400 text-xs">📊</span>
    return <span className="text-space-400 text-xs">📄</span>
  }

  // Status badge component
  const StatusBadge: React.FC<{ isVectorized: boolean; hasScrapeData?: boolean }> = ({
    isVectorized,
    hasScrapeData = true,
  }) => {
    if (!hasScrapeData) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">
          <AlertTriangle className="h-3 w-3" />
          No Data
        </span>
      )
    }
    if (isVectorized) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-neon-green/20 px-2 py-0.5 text-xs text-neon-green">
          <CheckCircle2 className="h-3 w-3" />
          Vectorized
        </span>
      )
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-space-700 px-2 py-0.5 text-xs text-space-400">
        <XCircle className="h-3 w-3" />
        Not Vectorized
      </span>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-display font-bold text-white">
            <Database className="h-7 w-7 text-neon-purple" />
            Vector Database
          </h2>
          <p className="text-space-400">
            View and manage vectorized scrape data for AI-powered analytics.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* View mode toggle */}
          <div className="flex rounded-lg border border-white/10 bg-space-900/50 p-1">
            <button
              type="button"
              onClick={() => setViewMode('individual')}
              className={`flex items-center gap-1 rounded-md px-3 py-1.5 text-sm transition-colors ${
                viewMode === 'individual'
                  ? 'bg-neon-purple/20 text-neon-purple'
                  : 'text-space-400 hover:text-white'
              }`}
            >
              <FileText className="h-4 w-4" />
              Individual
            </button>
            <button
              type="button"
              onClick={() => setViewMode('global')}
              className={`flex items-center gap-1 rounded-md px-3 py-1.5 text-sm transition-colors ${
                viewMode === 'global'
                  ? 'bg-neon-purple/20 text-neon-purple'
                  : 'text-space-400 hover:text-white'
              }`}
            >
              <Globe className="h-4 w-4" />
              Global View
            </button>
          </div>

          {!isServerRunning ? (
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              API offline
            </div>
          ) : null}
        </div>
      </div>

      {/* INDIVIDUAL VIEW */}
      {viewMode === 'individual' && (
        <>
          {/* Data Source Selector */}
          <CollapsibleSection
            title="Data Source"
            subtitle="Select a scrape folder to view or build its vector index"
          >
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[240px] flex-1">
                <label className="mb-1 block text-xs text-space-400">Scrape folder</label>
                <select
                  value={selectedOutputDir}
                  onChange={(e) => setSelectedOutputDir(e.target.value)}
                  className="futuristic-input w-full py-2"
                >
                  {sortedResults.length === 0 ? (
                    <option value="">No completed scrapes found</option>
                  ) : (
                    <>
                      <option value="">-- Select Video --</option>
                      {sortedResults.map((r) => (
                        <option key={r.id} value={r.outputDir}>
                          {r.title} ({r.videoId})
                        </option>
                      ))}
                    </>
                  )}
                </select>
              </div>
              <button
                type="button"
                onClick={() => void loadStatus()}
                disabled={isLoadingStatus || !serverUrl || !selectedOutputDir}
                className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
              >
                {isLoadingStatus ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Refresh Status
              </button>
            </div>

            {statusError ? (
              <pre className="mt-3 whitespace-pre-wrap rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
                {statusError}
              </pre>
            ) : null}
          </CollapsibleSection>

          {/* Status Card */}
          {ragStatus && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="space-y-4"
            >
              <CollapsibleSection
                title="Vectorization Status"
                subtitle={ragStatus.is_vectorized ? 'Data is vectorized and ready for AI chat' : 'Data needs to be vectorized'}
                defaultOpen
                headerRight={
                  <StatusBadge
                    isVectorized={ragStatus.is_vectorized}
                    hasScrapeData={!ragStatus.has_download_only && ragStatus.eligible_sources.length > 0}
                  />
                }
              >
                <div className="grid gap-4 md:grid-cols-2">
                  {/* Status Info */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-3">
                      <span className="text-sm text-space-400">Status</span>
                      <span className="text-sm font-medium text-white">
                        {ragStatus.is_vectorized ? 'Vectorized' : 'Not Vectorized'}
                      </span>
                    </div>

                    {ragStatus.is_vectorized && (
                      <>
                        <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-3">
                          <span className="text-sm text-space-400">Chunks</span>
                          <span className="text-sm font-medium text-neon-green">
                            {ragStatus.chunk_count.toLocaleString()}
                          </span>
                        </div>

                        <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-3">
                          <span className="text-sm text-space-400">Embed Model</span>
                          <span className="text-sm font-medium text-white">{ragStatus.embed_model}</span>
                        </div>

                        <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-3">
                          <span className="text-sm text-space-400">Dimensions</span>
                          <span className="text-sm font-medium text-white">{ragStatus.embed_dim}</span>
                        </div>

                        {ragStatus.last_updated && (
                          <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-3">
                            <span className="text-sm text-space-400">Last Updated</span>
                            <span className="text-sm font-medium text-space-300">
                              {new Date(ragStatus.last_updated).toLocaleString()}
                            </span>
                          </div>
                        )}
                      </>
                    )}

                    {!ragStatus.is_vectorized && (
                      <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-3">
                        <span className="text-sm text-space-400">Eligible Sources</span>
                        <span className="text-sm font-medium text-white">{ragStatus.eligible_sources.length} files</span>
                      </div>
                    )}
                  </div>

                  {/* Build Action */}
                  <div className="space-y-3">
                    {/* Download-only warning */}
                    {ragStatus.has_download_only && (
                      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200">
                        <div className="flex items-start gap-2">
                          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
                          <div>
                            <p className="font-medium">Download-only video detected</p>
                            <p className="mt-1 text-amber-300/80">
                              This video was downloaded via yt-dlp but has no scrape data. Run a scrape with
                              video/comments/transcript options first to create data for vectorization.
                            </p>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* No eligible sources warning */}
                    {!ragStatus.has_download_only && ragStatus.eligible_sources.length === 0 && (
                      <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
                        <div className="flex items-start gap-2">
                          <XCircle className="mt-0.5 h-5 w-5 shrink-0" />
                          <div>
                            <p className="font-medium">No scrape data found</p>
                            <p className="mt-1 text-rose-300/80">
                              No eligible scrape artifacts (video.json, comments.json, transcript, etc.) found.
                            </p>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Build Button */}
                    <button
                      type="button"
                      onClick={() => void handleBuild(ragStatus.is_vectorized)}
                      disabled={
                        isBuilding ||
                        ragBuildPhase === 'building' ||
                        !isServerRunning ||
                        ragStatus.has_download_only ||
                        ragStatus.eligible_sources.length === 0
                      }
                      className={`futuristic-btn w-full flex items-center justify-center gap-2 ${
                        ragStatus.is_vectorized ? '' : 'futuristic-btn-primary'
                      }`}
                    >
                      {ragBuildPhase === 'checking' ? (
                        <><Loader2 className="h-4 w-4 animate-spin" /> Checking...</>
                      ) : ragBuildPhase === 'building' ? (
                        <><Zap className="h-4 w-4 animate-pulse" /> Building...</>
                      ) : ragStatus.is_vectorized ? (
                        <><RefreshCw className="h-4 w-4" /> Rebuild Index</>
                      ) : (
                        <><Play className="h-4 w-4" /> Build Vector Index</>
                      )}
                    </button>

                    {/* Progress Bar */}
                    {ragBuildPhase === 'building' && (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-xs text-space-400">
                          <span>Progress</span>
                          <span>{ragBuildProgress}%</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-space-800">
                          <motion.div
                            initial={{ width: 0 }}
                            animate={{ width: `${ragBuildProgress}%` }}
                            className="h-full rounded-full bg-gradient-to-r from-neon-purple to-neon-blue"
                            transition={{ duration: 0.3 }}
                          />
                        </div>
                        <p className="text-xs text-space-500">
                          Generating embeddings via Ollama. This may take a few minutes for large datasets.
                        </p>
                      </div>
                    )}

                    {/* Build Error */}
                    {ragBuildError && (
                      <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
                        {ragBuildError}
                      </div>
                    )}

                    {/* Build Success */}
                    {ragBuildPhase === 'completed' && lastBuildResult?.success && (
                      <div className="rounded-lg border border-neon-green/40 bg-neon-green/10 p-3 text-sm text-neon-green">
                        <div className="flex items-center gap-2">
                          <CheckCircle2 className="h-4 w-4" />
                          <span>Build complete! {lastBuildResult.chunkCount} chunks indexed.</span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </CollapsibleSection>

              {/* Source Files */}
              {ragStatus.eligible_sources.length > 0 && (
                <CollapsibleSection title="Source Files" subtitle="Scrape artifacts used for vectorization" defaultOpen={false}>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {ragStatus.eligible_sources.map((source) => (
                      <div
                        key={source}
                        className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 p-2"
                      >
                        {getSourceIcon(source)}
                        <span className="text-sm text-space-300">{source}</span>
                      </div>
                    ))}
                  </div>
                  {ragStatus.missing_sources.length > 0 && (
                    <div className="mt-3">
                      <p className="mb-2 text-xs text-space-500">Missing (not required):</p>
                      <div className="flex flex-wrap gap-2">
                        {ragStatus.missing_sources.slice(0, 6).map((source) => (
                          <span
                            key={source}
                            className="rounded bg-space-800 px-2 py-1 text-xs text-space-500 line-through"
                          >
                            {source}
                          </span>
                        ))}
                        {ragStatus.missing_sources.length > 6 && (
                          <span className="text-xs text-space-500">
                            +{ragStatus.missing_sources.length - 6} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </CollapsibleSection>
              )}
            </motion.div>
          )}
        </>
      )}

      {/* GLOBAL VIEW */}
      {viewMode === 'global' && (
        <>
          {/* Stats Overview */}
          {globalStatus && (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="glass-card p-4">
                <p className="text-xs text-space-400">Total Videos</p>
                <p className="text-2xl font-bold text-white">{globalStatus.total_count}</p>
              </div>
              <div className="glass-card border-neon-green/20 bg-neon-green/5 p-4">
                <p className="text-xs text-neon-green">Vectorized</p>
                <p className="text-2xl font-bold text-neon-green">{globalStatus.vectorized_count}</p>
              </div>
              <div className="glass-card border-neon-purple/20 bg-neon-purple/5 p-4">
                <p className="text-xs text-neon-purple">Pending</p>
                <p className="text-2xl font-bold text-neon-purple">{globalStatus.pending_count}</p>
              </div>
              <div className="glass-card border-amber-500/20 bg-amber-500/5 p-4">
                <p className="text-xs text-amber-400">Download Only</p>
                <p className="text-2xl font-bold text-amber-400">{globalStatus.download_only_count}</p>
              </div>
            </div>
          )}

          {/* Filter and Actions */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-space-500" />
              <input
                type="text"
                placeholder="Filter by title, video ID, or folder..."
                value={globalFilter}
                onChange={(e) => setGlobalFilter(e.target.value)}
                className="futuristic-input w-full py-2 pl-10 pr-4"
              />
            </div>
            <button
              type="button"
              onClick={() => void loadGlobalStatus()}
              disabled={isLoadingGlobal || !isServerRunning}
              className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
            >
              {isLoadingGlobal ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Refresh
            </button>
          </div>

          {/* Global Table */}
          {globalError ? (
            <pre className="whitespace-pre-wrap rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
              {globalError}
            </pre>
          ) : (
            <div className="glass-card overflow-hidden">
              <div className="max-h-[500px] overflow-auto">
                <table className="w-full text-left text-sm">
                  <thead className="sticky top-0 z-10 bg-space-800/90 backdrop-blur">
                    <tr>
                      <th className="px-4 py-3 text-xs font-medium text-space-400">Status</th>
                      <th className="px-4 py-3 text-xs font-medium text-space-400">Video</th>
                      <th className="px-4 py-3 text-xs font-medium text-space-400">ID</th>
                      <th className="px-4 py-3 text-xs font-medium text-space-400">Chunks</th>
                      <th className="px-4 py-3 text-xs font-medium text-space-400">Model</th>
                      <th className="px-4 py-3 text-xs font-medium text-space-400">Last Updated</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {isLoadingGlobal && filteredGlobalVideos.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-4 py-8 text-center text-space-500">
                          <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />
                          Loading...
                        </td>
                      </tr>
                    ) : filteredGlobalVideos.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-4 py-8 text-center text-space-500">
                          {globalFilter ? 'No videos match your filter' : 'No videos found'}
                        </td>
                      </tr>
                    ) : (
                      filteredGlobalVideos.map((video) => (
                        <tr
                          key={video.output_dir}
                          className="hover:bg-white/5"
                        >
                          <td className="px-4 py-3">
                            <StatusBadge isVectorized={video.is_vectorized} hasScrapeData={video.has_scrape_data} />
                          </td>
                          <td className="px-4 py-3">
                            <p className="max-w-[200px] truncate font-medium text-white" title={video.title || undefined}>
                              {video.title || 'Untitled'}
                            </p>
                            <p className="text-xs text-space-500">
                              {video.output_dir.split(/[\\/]/).pop()}
                            </p>
                          </td>
                          <td className="px-4 py-3">
                            <code className="rounded bg-space-800 px-1.5 py-0.5 text-xs text-space-300">
                              {video.video_id || '-'}
                            </code>
                          </td>
                          <td className="px-4 py-3 text-space-300">
                            {video.is_vectorized ? video.chunk_count.toLocaleString() : '-'}
                          </td>
                          <td className="px-4 py-3 text-space-300">
                            {video.embed_model || '-'}
                          </td>
                          <td className="px-4 py-3 text-space-400">
                            {video.last_updated
                              ? new Date(video.last_updated).toLocaleDateString()
                              : '-'}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <div className="border-t border-white/10 px-4 py-2 text-xs text-space-500">
                Showing {filteredGlobalVideos.length} of {globalStatus?.videos.length || 0} videos
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default VectorDbView
