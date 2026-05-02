import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  ChevronRight,
  LineChart,
  Loader2,
  MessageSquare,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useScrapeStore } from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'
import { useVideoResults, type VideoResult } from '../hooks/useVideoResults'
import { openapiHasPostPath } from '../utils/analyticsApiProbe'
import { joinServerUrl } from '../utils/joinServerUrl'
import { readGuiAnalyticsLlmOverlay } from '../utils/guiAnalyticsLlmOverlay'
import { extractFastApiErrorDetail } from '../utils/fastApiErrorDetail'
import type { AnalyticsSnapshot, OllamaReportPayload } from '../types/analyticsShared'
import { useAnalyticsStore } from '../stores/analyticsStore'
import { ANALYTICS_METADATA_JOB_PREFIX } from '../constants/jobPrefixes'

async function augmentAnalyticsHttpError(serverUrl: string, res: Response, bodyText: string, routePath: string): Promise<string> {
  let msg = bodyText.trim() || `HTTP ${res.status}`
  if (res.status !== 404) {
    return msg
  }
  const probe = await openapiHasPostPath(serverUrl, routePath)
  if (probe === false) {
    msg += `\n\nThis API does not expose POST ${routePath}. The running Python backend is probably outdated. Use Debug → Restart Server (or rebuild the bundled API), then try again.`
  } else if (probe === null) {
    msg +=
      '\n\nCould not read /openapi.json to verify routes. Restart the Python API from Debug, or confirm nothing else is listening on the reported URL/port.'
  } else {
    msg +=
      '\n\n404 while OpenAPI lists this route — verify the server URL/port in Debug matches the API you intend (only one process should serve this app).'
  }
  return msg
}

const JOB_POLL_INTERVAL_MS = 2000
const JOB_POLL_TIMEOUT_MS = 45 * 60 * 1000

function normalizeOutputDirKey(dir: string): string {
  return dir.replace(/[\\/]+$/, '').replace(/\\/g, '/')
}

function formatMetadataHistoryLabel(capturedAt: string): string {
  const ms = Date.parse(capturedAt)
  if (!Number.isFinite(ms)) {
    return capturedAt.trim() || 'Unknown date'
  }
  return new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** Missing numeric fields in a history row become null in the GUI; do not plot those as zero (false dip). */
function coalesceNumericSeriesForLineChart(values: Array<number | null | undefined>): number[] {
  const nums: Array<number | null> = values.map((v) =>
    typeof v === 'number' && Number.isFinite(v) ? v : null
  )
  const n = nums.length
  if (n === 0) {
    return []
  }
  if (nums.every((v) => v === null)) {
    return nums.map(() => 0)
  }
  const work: Array<number | null> = [...nums]
  let last: number | null = null
  for (let i = 0; i < n; i++) {
    if (work[i] !== null) {
      last = work[i]
    } else if (last !== null) {
      work[i] = last
    }
  }
  let prev: number | null = null
  for (let i = n - 1; i >= 0; i--) {
    if (work[i] !== null) {
      prev = work[i]
    } else if (prev !== null) {
      work[i] = prev
    }
  }
  return work.map((v) => (v === null ? 0 : v))
}

function firstLastFiniteInSeries(nums: Array<number | null>): { first: number | null; last: number | null } {
  const first = nums.find((v) => v !== null) ?? null
  let last: number | null = null
  for (let i = nums.length - 1; i >= 0; i--) {
    if (nums[i] !== null) {
      last = nums[i]
      break
    }
  }
  return { first, last }
}

function resolveYoutubeWatchUrl(result: VideoResult | null): string | null {
  if (!result) {
    return null
  }
  const u = result.url?.trim() ?? ''
  if (u && /^https?:\/\//i.test(u) && (u.includes('youtube.com') || u.includes('youtu.be'))) {
    return u
  }
  const vid = result.videoId?.trim() ?? ''
  if (vid.length > 0) {
    return `https://www.youtube.com/watch?v=${encodeURIComponent(vid)}`
  }
  return null
}

async function pollJobUntilTerminal(serverUrl: string, jobId: string): Promise<{ ok: boolean; error?: string }> {
  const deadline = Date.now() + JOB_POLL_TIMEOUT_MS
  while (Date.now() < deadline) {
    const res = await fetch(joinServerUrl(serverUrl, `/jobs/${jobId}`))
    if (!res.ok) {
      const text = await res.text()
      const detail = extractFastApiErrorDetail(text)
      return { ok: false, error: detail ?? `HTTP ${res.status}` }
    }
    const job = (await res.json()) as { status?: string; error?: string }
    const st = job.status
    if (st === 'completed') {
      return { ok: true }
    }
    if (st === 'failed') {
      return { ok: false, error: job.error?.trim() || 'Job failed' }
    }
    if (st === 'cancelled') {
      return { ok: false, error: 'Job cancelled' }
    }
    await new Promise((r) => setTimeout(r, JOB_POLL_INTERVAL_MS))
  }
  return { ok: false, error: 'Timed out waiting for scrape job' }
}

interface AnalyticsViewProps {
  onNavigateToGallery: () => void
}

function CollapsibleSection({
  title,
  subtitle,
  defaultOpen = true,
  className,
  contentClassName = 'p-5',
  children,
  headerRight,
  compact = false,
}: {
  title: React.ReactNode
  subtitle?: React.ReactNode
  defaultOpen?: boolean
  className?: string
  contentClassName?: string
  children: React.ReactNode
  headerRight?: React.ReactNode
  /** Smaller header + type scale for nested blocks (e.g. LLM brief subsections). */
  compact?: boolean
}): React.ReactElement {
  const [open, setOpen] = useState(defaultOpen)
  const headerPad = compact ? 'px-3 py-2' : 'px-5 py-3'
  const titleCls = compact ? 'block text-sm font-semibold text-white' : 'block text-lg font-semibold text-white'
  const chevronCls = compact ? 'h-4 w-4' : 'h-5 w-5'
  return (
    <div className={className ?? 'glass-card overflow-hidden'}>
      <div className={`flex items-start gap-2 border-b border-white/10 ${headerPad} ${headerRight ? 'flex-wrap' : ''}`}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-start gap-2 rounded-md px-2 py-1 text-left -mx-2 hover:bg-white/5"
          aria-expanded={open}
        >
          <span className={`mt-0.5 shrink-0 text-space-400 ${compact ? 'mt-px' : ''}`}>
            {open ? <ChevronDown className={chevronCls} /> : <ChevronRight className={chevronCls} />}
          </span>
          <span className="min-w-0 flex-1">
            <span className={titleCls}>{title}</span>
            {subtitle ? <span className="mt-0.5 block text-xs text-space-500">{subtitle}</span> : null}
          </span>
        </button>
        {headerRight ? <div className="flex shrink-0 flex-wrap items-center gap-2">{headerRight}</div> : null}
      </div>
      {open ? <div className={contentClassName}>{children}</div> : null}
    </div>
  )
}

function Sparkline({
  values,
  label,
  tone,
}: {
  values: Array<number | null | undefined>
  label: string
  tone: string
}): React.ReactElement | null {
  const nums = values.map((v) => (typeof v === 'number' && Number.isFinite(v) ? v : null))
  if (nums.every((v) => v === null)) {
    return (
      <div className="rounded-lg border border-white/10 bg-white/5 p-3">
        <p className="text-xs text-space-400">{label}</p>
        <p className="mt-2 text-sm text-space-500">No numeric series</p>
      </div>
    )
  }
  const { first: firstFinite, last: lastFinite } = firstLastFiniteInSeries(nums)
  const resolved = coalesceNumericSeriesForLineChart(values)
  let low = Math.min(...resolved)
  let high = Math.max(...resolved)
  let span = high - low
  if (span === 0) {
    const pad = Math.max(Math.abs(high) * 0.02, 1)
    low -= pad
    high += pad
    span = high - low
  } else {
    const pad = span * 0.08
    low -= pad
    high += pad
    span = high - low
  }
  const w = 240
  const h = 56
  const step = nums.length > 1 ? w / (nums.length - 1) : w
  const points = resolved.map((val, i) => {
    const x = i * step
    const y = h - ((val - low) / span) * (h - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3">
      <p className="text-xs text-space-400">{label}</p>
      <svg width={w} height={h} className={`mt-2 overflow-visible ${tone}`}>
        <polyline
          fill="none"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          stroke="currentColor"
          points={points.join(' ')}
        />
      </svg>
      <p className="mt-1 font-mono text-[11px] text-space-500">
        first → last: {firstFinite ?? '—'} → {lastFinite ?? '—'}
      </p>
    </div>
  )
}

function HorizontalBars({
  buckets,
  title,
}: {
  buckets: Array<{ label: string; count: number }>
  title: string
}): React.ReactElement {
  const max = Math.max(...buckets.map((b) => b.count), 1)
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-4">
      <h4 className="text-sm font-semibold text-white">{title}</h4>
      <div className="mt-3 space-y-2">
        {buckets.map((b) => (
          <div key={b.label}>
            <div className="flex justify-between text-xs text-space-400">
              <span>{b.label}</span>
              <span>{b.count}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-space-800">
              <div
                className="h-full rounded-full bg-gradient-to-r from-neon-blue to-neon-purple"
                style={{ width: `${(b.count / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const AnalyticsView: React.FC<AnalyticsViewProps> = ({ onNavigateToGallery }) => {
  const jobs = useScrapeStore((s) => s.jobs)
  const addJob = useScrapeStore((s) => s.addJob)
  const addJobLog = useScrapeStore((s) => s.addJobLog)
  const updateJob = useScrapeStore((s) => s.updateJob)
  const setActiveJob = useScrapeStore((s) => s.setActiveJob)
  const galleryDiskRevisionBump = useScrapeStore((s) => s.galleryDiskRevisionBump)
  const bumpGalleryDiskRevision = useScrapeStore((s) => s.bumpGalleryDiskRevision)
  const maxComments = useScrapeStore((s) => s.scrapeOptions.maxComments)
  const results = useVideoResults(jobs, galleryDiskRevisionBump)
  const serverUrl = useAppStore((s) => s.serverUrl)
  const isServerRunning = useAppStore((s) => s.isServerRunning)

  const selectedDir = useAnalyticsStore((s) => s.selectedOutputDir)
  const setSelectedOutputDir = useAnalyticsStore((s) => s.setSelectedOutputDir)
  const snapshot = useAnalyticsStore((s) => s.snapshot)
  const setSnapshot = useAnalyticsStore((s) => s.setSnapshot)
  const loadError = useAnalyticsStore((s) => s.loadError)
  const setLoadError = useAnalyticsStore((s) => s.setLoadError)
  const isFetchingSnapshot = useAnalyticsStore((s) => s.isFetchingSnapshot)
  const setIsFetchingSnapshot = useAnalyticsStore((s) => s.setIsFetchingSnapshot)
  const llmReport = useAnalyticsStore((s) => s.llmReport)
  const setLlmReport = useAnalyticsStore((s) => s.setLlmReport)
  const llmError = useAnalyticsStore((s) => s.llmError)
  const setLlmError = useAnalyticsStore((s) => s.setLlmError)

  const [llmLoading, setLlmLoading] = useState(false)

  const [metaRefreshing, setMetaRefreshing] = useState(false)
  const [commentsRefreshing, setCommentsRefreshing] = useState(false)
  const [allRefreshing, setAllRefreshing] = useState(false)
  /** `null` = latest on-disk snapshot; otherwise index into `metadata_history` for chart slice + public metrics. */
  const [metadataHistoryViewIndex, setMetadataHistoryViewIndex] = useState<number | null>(null)

  const sortedResults = useMemo(
    () => [...results].sort((a, b) => a.title.localeCompare(b.title)),
    [results]
  )

  useEffect(() => {
    if (!selectedDir && sortedResults.length > 0) {
      setSelectedOutputDir(sortedResults[0].outputDir, 'auto')
    }
  }, [selectedDir, sortedResults, setSelectedOutputDir])

  const fetchSnapshot = useCallback(async (options?: { silent?: boolean }) => {
    if (!serverUrl || !selectedDir) {
      toast.error('Pick a folder and ensure the API server is running.')
      return
    }
    const silent = Boolean(options?.silent)
    if (!silent) {
      setIsFetchingSnapshot(true)
    }
    setLoadError(null)
    try {
      const res = await fetch(joinServerUrl(serverUrl, '/analytics/snapshot'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ output_dir: selectedDir }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(await augmentAnalyticsHttpError(serverUrl, res, text, '/analytics/snapshot'))
      }
      const data = (await res.json()) as AnalyticsSnapshot
      setSnapshot(data)
      if (!silent) {
        toast.success('Analytics loaded')
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setLoadError(msg)
      toast.error(silent ? msg : 'Could not load analytics')
    } finally {
      if (!silent) {
        setIsFetchingSnapshot(false)
      }
    }
  }, [serverUrl, selectedDir, setIsFetchingSnapshot, setLoadError, setSnapshot])

  const fetchLlm = useCallback(
    async (forceRefresh: boolean, options?: { silent?: boolean }) => {
      if (!serverUrl || !selectedDir) {
        if (!options?.silent) {
          toast.error('Pick a folder and ensure the API server is running.')
        }
        return
      }
      const silent = Boolean(options?.silent)
      setLlmLoading(true)
      setLlmError(null)
      try {
        const guiOverlay = await readGuiAnalyticsLlmOverlay()
        const res = await fetch(joinServerUrl(serverUrl, '/analytics/ollama-report'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            output_dir: selectedDir,
            force_refresh: forceRefresh,
            gui_llm_overlay: guiOverlay ?? {},
          }),
        })
        if (!res.ok) {
          const text = await res.text()
          const extracted = extractFastApiErrorDetail(text)
          const hint = await augmentAnalyticsHttpError(serverUrl, res, text, '/analytics/ollama-report')
          throw new Error(extracted ?? hint)
        }
        const data = (await res.json()) as OllamaReportPayload
        setLlmReport(data)
        if (!silent) {
          toast.success(data.from_cache ? 'Loaded cached AI brief' : 'Generated AI brief')
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        setLlmError(msg)
        if (!silent) {
          toast.error('AI brief failed — check LLM Settings (remote URL, model) and API error detail below.')
        }
      } finally {
        setLlmLoading(false)
      }
    },
    [serverUrl, selectedDir]
  )

  /** After analytics snapshot loads, try cache (or generate) without toasts; manual buttons still available. */
  useEffect(() => {
    if (!snapshot || !serverUrl || !selectedDir || !isServerRunning) {
      return
    }
    const dirKey = normalizeOutputDirKey(selectedDir)
    if (normalizeOutputDirKey(snapshot.output_dir) !== dirKey) {
      return
    }
    void fetchLlm(false, { silent: true })
  }, [snapshot, serverUrl, selectedDir, isServerRunning, fetchLlm])

  const selectedResult = useMemo(
    () =>
      sortedResults.find((r) => normalizeOutputDirKey(r.outputDir) === normalizeOutputDirKey(selectedDir)) ?? null,
    [sortedResults, selectedDir]
  )

  const watchUrl = useMemo(() => resolveYoutubeWatchUrl(selectedResult), [selectedResult])

  const anyQuickRefreshBusy = metaRefreshing || commentsRefreshing || allRefreshing

  const quickRefreshDisabled =
    !serverUrl || !isServerRunning || !selectedDir || !watchUrl || isFetchingSnapshot || anyQuickRefreshBusy

  const executeMetadataRefreshCore = useCallback(async () => {
    if (!serverUrl || !selectedDir || !watchUrl) {
      throw new Error('Missing server URL, folder, or video URL.')
    }
    const res = await fetch(joinServerUrl(serverUrl, '/metadata/refresh-batch'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: [{ output_dir: selectedDir, url: watchUrl }],
      }),
    })
    const text = await res.text()
    if (!res.ok) {
      throw new Error(await augmentAnalyticsHttpError(serverUrl, res, text, '/metadata/refresh-batch'))
    }
    let body: { results?: Array<{ output_dir: string; ok: boolean; error?: string | null }> }
    try {
      body = JSON.parse(text) as typeof body
    } catch {
      throw new Error('Invalid JSON from metadata refresh')
    }
    const row = body.results?.[0]
    if (!row?.ok) {
      throw new Error(row?.error?.trim() || 'Metadata refresh failed')
    }
    bumpGalleryDiskRevision()
  }, [serverUrl, selectedDir, watchUrl, bumpGalleryDiskRevision])

  const runTrackedMetadataRefresh = useCallback(async () => {
    if (!watchUrl || !selectedDir) {
      throw new Error('Missing folder or video URL.')
    }
    const jobId = `${ANALYTICS_METADATA_JOB_PREFIX}${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`}`
    addJob(
      {
        id: jobId,
        url: watchUrl,
        videoTitle: 'Analytics · video details',
        status: 'running',
        progress: 20,
        type: 'video',
        operations: ['video'],
        outputDir: selectedDir,
        startedAt: new Date().toISOString(),
      },
      { skipDashboardBump: true }
    )
    addJobLog(jobId, {
      level: 'info',
      message: 'Refreshing video details via /metadata/refresh-batch',
      timestamp: new Date().toISOString(),
    })
    try {
      await executeMetadataRefreshCore()
      updateJob(jobId, {
        status: 'completed',
        progress: 100,
        completedAt: new Date().toISOString(),
      })
      addJobLog(jobId, {
        level: 'info',
        message: 'Video details updated (metadata_history / video.json).',
        timestamp: new Date().toISOString(),
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      updateJob(jobId, {
        status: 'failed',
        progress: 100,
        error: msg,
        completedAt: new Date().toISOString(),
      })
      addJobLog(jobId, {
        level: 'error',
        message: msg,
        timestamp: new Date().toISOString(),
      })
      throw e
    }
  }, [
    watchUrl,
    selectedDir,
    addJob,
    addJobLog,
    updateJob,
    executeMetadataRefreshCore,
  ])

  const executeCommentsRefreshCore = useCallback(async () => {
    if (!serverUrl || !selectedDir || !watchUrl) {
      throw new Error('Missing server URL, folder, or video URL.')
    }
    const res = await fetch(joinServerUrl(serverUrl, '/scrape/video'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: watchUrl,
        include_video: false,
        include_comments: true,
        include_transcript: false,
        include_thumbnails: false,
        include_download: false,
        max_comments: maxComments,
        comments_snapshot_before_write: true,
        comments_fetch_all: true,
        transcript_format: 'txt',
        video_quality: 'best',
      }),
    })
    const text = await res.text()
    if (!res.ok) {
      throw new Error(await augmentAnalyticsHttpError(serverUrl, res, text, '/scrape/video'))
    }
    let data: { job_id?: string; output_dir?: string }
    try {
      data = JSON.parse(text) as { job_id?: string; output_dir?: string }
    } catch {
      throw new Error('Invalid JSON when starting comment scrape')
    }
    const jobId = data.job_id
    if (!jobId) {
      throw new Error('No job_id returned when starting comment scrape')
    }
    const outputDir =
      typeof data.output_dir === 'string' && data.output_dir.trim().length > 0 ? data.output_dir : selectedDir
    if (normalizeOutputDirKey(outputDir) !== normalizeOutputDirKey(selectedDir)) {
      toast(
        `Comments were written to ${outputDir}, which differs from the folder selected above. Pick that folder or use the standard output layout so analytics matches the scrape.`,
        { duration: 9000 }
      )
    }
    addJob({
      id: jobId,
      url: watchUrl,
      status: 'running',
      progress: 0,
      type: 'comments',
      operations: ['comments'],
      outputDir,
      startedAt: new Date().toISOString(),
    })
    setActiveJob(jobId)
    const outcome = await pollJobUntilTerminal(serverUrl, jobId)
    if (!outcome.ok) {
      const errMsg = outcome.error ?? 'Comment scrape failed'
      updateJob(jobId, {
        status: 'failed',
        error: errMsg,
        completedAt: new Date().toISOString(),
        progress: 100,
      })
      throw new Error(errMsg)
    }
    updateJob(jobId, {
      status: 'completed',
      progress: 100,
      completedAt: new Date().toISOString(),
      outputDir,
    })
    bumpGalleryDiskRevision()
  }, [
    serverUrl,
    selectedDir,
    watchUrl,
    maxComments,
    bumpGalleryDiskRevision,
    addJob,
    setActiveJob,
    updateJob,
  ])

  const handleRefreshVideoMetadata = useCallback(async () => {
    const loadingToast = toast.loading('Refreshing video details…')
    setMetaRefreshing(true)
    try {
      await runTrackedMetadataRefresh()
      toast.success('Video details refreshed', { id: loadingToast })
      await fetchSnapshot({ silent: true })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id: loadingToast })
    } finally {
      setMetaRefreshing(false)
    }
  }, [runTrackedMetadataRefresh, fetchSnapshot])

  const handleRefreshComments = useCallback(async () => {
    const loadingToast = toast.loading('Refreshing comments (see Scrape Jobs for live progress)…')
    setCommentsRefreshing(true)
    try {
      await executeCommentsRefreshCore()
      toast.success('Comments refreshed', { id: loadingToast })
      await fetchSnapshot({ silent: true })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id: loadingToast })
    } finally {
      setCommentsRefreshing(false)
    }
  }, [executeCommentsRefreshCore, fetchSnapshot])

  const handleRefreshAll = useCallback(async () => {
    const loadingToast = toast.loading('Refreshing video details, then comments…')
    setAllRefreshing(true)
    try {
      await runTrackedMetadataRefresh()
      await executeCommentsRefreshCore()
      toast.success('Video details and comments refreshed', { id: loadingToast })
      await fetchSnapshot({ silent: true })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { id: loadingToast })
    } finally {
      setAllRefreshing(false)
    }
  }, [runTrackedMetadataRefresh, executeCommentsRefreshCore, fetchSnapshot])

  const hist = snapshot?.metadata_history ?? []

  useEffect(() => {
    setMetadataHistoryViewIndex(null)
  }, [selectedDir, snapshot?.output_dir])

  useEffect(() => {
    if (metadataHistoryViewIndex !== null && metadataHistoryViewIndex >= hist.length) {
      setMetadataHistoryViewIndex(null)
    }
  }, [hist.length, metadataHistoryViewIndex])

  const histForCharts = useMemo(() => {
    if (metadataHistoryViewIndex === null) {
      return hist
    }
    return hist.slice(0, metadataHistoryViewIndex + 1)
  }, [hist, metadataHistoryViewIndex])

  const historyPoint =
    metadataHistoryViewIndex !== null ? hist[metadataHistoryViewIndex] ?? null : null

  const views = histForCharts.map((h) => h.view_count)
  const likes = histForCharts.map((h) => h.like_count)
  const dislikes = histForCharts.map((h) => h.dislike_count)
  const pubComments = histForCharts.map((h) => h.comment_count)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-display font-bold text-white">
            <BarChart3 className="h-7 w-7 text-neon-purple" />
            Analytics
          </h2>
          <p className="text-space-400">
            Deterministic stats from scrape files; optional LLM synthesis (configure in Settings).
          </p>
        </div>
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          {snapshot && hist.length > 0 ? (
            <div className="flex flex-col gap-1 sm:items-end">
              <label htmlFor="analytics-metadata-snapshot" className="text-xs text-space-400">
                Metadata snapshot
              </label>
              <select
                id="analytics-metadata-snapshot"
                value={metadataHistoryViewIndex === null ? 'latest' : String(metadataHistoryViewIndex)}
                onChange={(e) => {
                  const v = e.target.value
                  if (v === 'latest') {
                    setMetadataHistoryViewIndex(null)
                    return
                  }
                  const idx = Number.parseInt(v, 10)
                  if (!Number.isFinite(idx) || idx < 0 || idx >= hist.length) {
                    setMetadataHistoryViewIndex(null)
                    return
                  }
                  setMetadataHistoryViewIndex(idx)
                }}
                className="futuristic-input min-w-[14rem] py-2 text-sm"
              >
                <option value="latest">Latest (current files)</option>
                {[...hist.keys()]
                  .reverse()
                  .map((i) => (
                    <option key={`${hist[i].captured_at}-${i}`} value={String(i)}>
                      {formatMetadataHistoryLabel(hist[i].captured_at)}
                    </option>
                  ))}
              </select>
            </div>
          ) : null}
          {!isServerRunning ? (
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              API offline — start the backend to load analytics.
            </div>
          ) : null}
        </div>
      </div>

      <CollapsibleSection
        title="Data source"
        subtitle="Choose a scrape folder and fetch a snapshot from the API."
        contentClassName="p-5 space-y-4"
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[240px] flex-1">
            <label className="block text-xs text-space-400 mb-1">Scrape folder</label>
            <select
              value={selectedDir}
              disabled={anyQuickRefreshBusy}
              onChange={(e) => {
                setSelectedOutputDir(e.target.value, 'user-change')
              }}
              className="futuristic-input w-full py-2"
            >
              {sortedResults.length === 0 ? (
                <option value="">No completed scrapes found</option>
              ) : (
                sortedResults.map((r) => (
                  <option key={r.id} value={r.outputDir}>
                    {r.title} ({r.videoId})
                  </option>
                ))
              )}
            </select>
          </div>
          <button
            type="button"
            onClick={() => void fetchSnapshot()}
            disabled={isFetchingSnapshot || !serverUrl || !selectedDir}
            className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
          >
            {isFetchingSnapshot ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Load data
          </button>
        </div>

        {snapshot?.metadata_history_points !== undefined && snapshot.metadata_history_points < 2 ? (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-neon-blue/30 bg-neon-blue/10 px-4 py-3 text-sm text-space-200">
            <LineChart className="h-5 w-5 shrink-0 text-neon-blue" />
            <span>
              Trend charts need at least two metadata snapshots. After you <strong className="text-space-300">Load data</strong>, use{' '}
              <strong className="text-space-300">Refresh video details</strong> under Performance over time,{' '}
              <button
                type="button"
                className="text-neon-cyan underline hover:text-white"
                onClick={onNavigateToGallery}
              >
                Video Gallery
              </button>{' '}
              for batch runs, or any flow that appends <code className="text-neon-purple">metadata_history.jsonl</code>.
            </span>
          </div>
        ) : null}

        {loadError ? (
          <pre className="whitespace-pre-wrap rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
            {loadError}
          </pre>
        ) : null}
      </CollapsibleSection>

      {snapshot ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-6"
        >
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <CollapsibleSection
              className="glass-card overflow-hidden"
              title="Video snapshot"
              subtitle={
                historyPoint
                  ? `Public metrics as of ${formatMetadataHistoryLabel(historyPoint.captured_at)}. Title and description from latest video.json.`
                  : 'Latest metrics from video.json.'
              }
              contentClassName="space-y-3 p-5"
            >
              {snapshot.video_metrics || historyPoint ? (
                <div className="space-y-3 text-sm text-space-300">
                  <ul className="space-y-1">
                    <li>
                      <span className="text-space-500">Title:</span> {snapshot.video_metrics?.title ?? '—'}
                    </li>
                    <li>
                      <span className="text-space-500">Channel:</span>{' '}
                      {snapshot.video_metrics?.channel_title ?? '—'}
                    </li>
                    <li>
                      <span className="text-space-500">Views:</span>{' '}
                      {(historyPoint?.view_count ?? snapshot.video_metrics?.view_count)?.toLocaleString() ?? '—'}
                    </li>
                    <li>
                      <span className="text-space-500">Likes / Dislikes:</span>{' '}
                      {(historyPoint?.like_count ?? snapshot.video_metrics?.like_count)?.toLocaleString() ?? '—'} /{' '}
                      {(historyPoint?.dislike_count ?? snapshot.video_metrics?.dislike_count)?.toLocaleString() ?? '—'}
                    </li>
                    <li>
                      <span className="text-space-500">Comment count (YouTube):</span>{' '}
                      {(historyPoint?.comment_count ?? snapshot.video_metrics?.comment_count)?.toLocaleString() ??
                        '—'}
                    </li>
                    {snapshot.comment_stats ? (
                      <li>
                        <span className="text-space-500">Comments scraped (file):</span>{' '}
                        {snapshot.comment_stats.total_flat.toLocaleString()}
                        {historyPoint ? (
                          <span className="mt-1 block text-xs text-space-500">
                            From the current comments file, not the metadata date above.
                          </span>
                        ) : null}
                      </li>
                    ) : null}
                  </ul>
                  {snapshot.video_metrics ? (
                    <div>
                      <div className="text-space-500">Description</div>
                      <div className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-white/10 bg-black/20 p-3 text-space-300">
                        {snapshot.video_metrics.description?.trim() ? snapshot.video_metrics.description : '—'}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="text-space-500 text-sm">No video.json metadata.</p>
              )}
            </CollapsibleSection>

            <div className="flex min-w-0 flex-col gap-4">
              <CollapsibleSection
                className="glass-card overflow-hidden"
                title="Performance over time"
                subtitle="Sparklines from metadata_history.jsonl."
                contentClassName="p-5"
              >
                {hist.length === 0 ? (
                  <p className="text-sm text-space-500">No metadata history file.</p>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Sparkline values={views} label="Views" tone="text-neon-blue" />
                    <Sparkline values={likes} label="Likes" tone="text-neon-green" />
                    <Sparkline values={dislikes} label="Dislikes" tone="text-amber-400" />
                    <Sparkline values={pubComments} label="Public comment total" tone="text-neon-purple" />
                  </div>
                )}
                <p className="mt-3 text-xs text-space-500">
                  Points: {histForCharts.length}
                  {historyPoint ? ` of ${hist.length}` : ''} (from metadata_history.jsonl).
                  {historyPoint
                    ? ' Trend is clipped to the selected capture.'
                    : ' Capture times align with gallery refresh runs.'}
                </p>
              </CollapsibleSection>

              <div className="glass-card space-y-3 overflow-hidden p-4">
                {!watchUrl && selectedDir ? (
                  <p className="text-sm text-amber-200/90">
                    Could not resolve a YouTube URL for this folder. Complete a scrape with a watch link, or ensure{' '}
                    <code className="text-neon-purple">video.json</code> / discovery provides a video id.
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={quickRefreshDisabled}
                    onClick={() => void handleRefreshVideoMetadata()}
                    className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
                  >
                    {metaRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    Refresh video details
                  </button>
                  <button
                    type="button"
                    disabled={quickRefreshDisabled}
                    onClick={() => void handleRefreshComments()}
                    className="futuristic-btn flex items-center gap-2"
                  >
                    {commentsRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquare className="h-4 w-4" />}
                    Refresh comments
                  </button>
                  <button
                    type="button"
                    disabled={quickRefreshDisabled}
                    onClick={() => void handleRefreshAll()}
                    className="futuristic-btn flex items-center gap-2 border border-neon-cyan/35"
                  >
                    {allRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    Refresh all
                  </button>
                </div>
              </div>
            </div>
          </div>

          {snapshot.notes.length > 0 ? (
            <CollapsibleSection
              title="Notes"
              subtitle="Snapshot warnings and file hints from the API."
              contentClassName="p-5"
            >
              <ul className="list-disc space-y-1 pl-5 text-sm text-space-400">
                {snapshot.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </CollapsibleSection>
          ) : null}

          {snapshot.comment_stats ? (
            <CollapsibleSection
              title="Comment volume & likes"
              subtitle="Buckets and daily UTC volume from scraped comments."
              contentClassName="p-5"
              defaultOpen={false}
            >
              <div className="grid gap-4 lg:grid-cols-3">
                <HorizontalBars buckets={snapshot.comment_stats.like_buckets} title="Comment likes (bucket)" />
                <div className="rounded-lg border border-white/10 bg-white/5 p-4 lg:col-span-2">
                  <h4 className="text-sm font-semibold text-white">Comments per day (UTC)</h4>
                  {snapshot.comment_stats.volume_by_day.length === 0 ? (
                    <p className="mt-2 text-sm text-space-500">No dated comments.</p>
                  ) : (
                    <div className="mt-3 max-h-56 space-y-2 overflow-y-auto pr-1">
                      {(() => {
                        const max = Math.max(...snapshot.comment_stats.volume_by_day.map((b) => b.count), 1)
                        return snapshot.comment_stats.volume_by_day.map((b) => (
                          <div key={b.bucket_start}>
                            <div className="flex justify-between text-xs text-space-400">
                              <span>{b.bucket_start}</span>
                              <span>{b.count}</span>
                            </div>
                            <div className="mt-1 h-2 overflow-hidden rounded-full bg-space-800">
                              <div
                                className="h-full rounded-full bg-neon-cyan/80"
                                style={{ width: `${(b.count / max) * 100}%` }}
                              />
                            </div>
                          </div>
                        ))
                      })()}
                    </div>
                  )}
                  <p className="mt-2 text-xs text-space-500">
                    Flat comments: {snapshot.comment_stats.total_flat}, with timestamp:{' '}
                    {snapshot.comment_stats.with_published_at}, replies:{' '}
                    {snapshot.comment_stats.reply_count ?? '—'}
                  </p>
                </div>
              </div>
            </CollapsibleSection>
          ) : null}

          {snapshot.comment_stats && snapshot.comment_stats.top_authors.length > 0 ? (
            <CollapsibleSection
              title="Top authors (volume)"
              contentClassName="p-0"
              defaultOpen={false}
            >
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-white/5 text-space-400">
                    <tr>
                      <th className="px-5 py-2 font-medium">Author</th>
                      <th className="px-5 py-2 font-medium">Comments</th>
                      <th className="px-5 py-2 font-medium">Σ likes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.comment_stats.top_authors.map((a) => (
                      <tr key={a.author} className="border-t border-white/5">
                        <td className="px-5 py-2 text-space-200">{a.author}</td>
                        <td className="px-5 py-2 text-space-300">{a.comment_count}</td>
                        <td className="px-5 py-2 text-space-300">{a.total_likes ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CollapsibleSection>
          ) : null}

          {snapshot.keywords.length > 0 ? (
            <CollapsibleSection
              title="Top tokens (English heuristic)"
              subtitle="Naïve word frequencies — supplement with the AI brief for themes."
              contentClassName="p-0"
              defaultOpen={false}
            >
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-white/5 text-space-400">
                    <tr>
                      <th className="px-5 py-2 font-medium">Term</th>
                      <th className="px-5 py-2 font-medium">Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.keywords.map((k) => (
                      <tr key={k.term} className="border-t border-white/5">
                        <td className="px-5 py-2 font-mono text-neon-cyan">{k.term}</td>
                        <td className="px-5 py-2 text-space-300">{k.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CollapsibleSection>
          ) : null}

          <CollapsibleSection
            className="glass-card overflow-hidden border border-neon-purple/25"
            title={
              <span className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-neon-purple" />
                AI macro brief (Ollama)
              </span>
            }
            subtitle="Optional LLM synthesis from scraped comments (configure Ollama in Settings)."
            contentClassName="space-y-4 p-5"
            defaultOpen
            headerRight={
              <>
                <button
                  type="button"
                  disabled={llmLoading || !serverUrl || !selectedDir}
                  onClick={() => void fetchLlm(false)}
                  className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
                >
                  {llmLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Generate / load cached
                </button>
                <button
                  type="button"
                  disabled={llmLoading || !serverUrl || !selectedDir}
                  onClick={() => void fetchLlm(true)}
                  className="futuristic-btn flex items-center gap-2"
                >
                  Force refresh
                </button>
              </>
            }
          >
            <p className="text-sm text-space-400">
              Audience reactions inferred from <strong className="text-space-300">your scraped comments only</strong>{' '}
              (themes, tone, splits — language patterns, not clinical diagnoses). Requires local Ollama (
              <code className="text-space-300">YOUTUBE_SCRAPE_OLLAMA_*</code>). Use{' '}
              <strong className="text-space-300">Force refresh</strong> after updates so prompts apply.
            </p>

            {llmError ? (
              <pre className="whitespace-pre-wrap rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
                {llmError}
              </pre>
            ) : null}

            {llmReport ? (
              <div className="space-y-3 rounded-lg border border-white/10 bg-space-900/40 p-4">
                <p className="text-xs text-space-500">
                  Model {llmReport.model} · {llmReport.generated_at}{' '}
                  {llmReport.from_cache ? '(cache)' : '(fresh)'}
                </p>
                <CollapsibleSection
                  className="rounded-lg border border-white/10 bg-space-950/30 overflow-hidden"
                  title="Themes"
                  defaultOpen
                  compact
                  contentClassName="border-t border-white/5 px-4 py-3"
                >
                  <ul className="list-disc pl-5 text-sm text-space-300">
                    {llmReport.brief.themes.map((t, i) => (
                      <li key={`${i}-${t}`}>{t}</li>
                    ))}
                  </ul>
                </CollapsibleSection>
                <CollapsibleSection
                  className="rounded-lg border border-white/10 bg-space-950/30 overflow-hidden"
                  title={<span className="text-neon-blue">Sentiment (overview)</span>}
                  defaultOpen
                  compact
                  contentClassName="border-t border-white/5 px-4 py-3"
                >
                  <p className="text-sm text-space-300">{llmReport.brief.sentiment_overview}</p>
                </CollapsibleSection>
                <div className="grid items-start gap-3 md:grid-cols-2">
                  <CollapsibleSection
                    className="rounded-lg border border-white/10 bg-space-950/30 overflow-hidden"
                    title={<span className="text-neon-green">Suggestions / requests</span>}
                    defaultOpen
                    compact
                    contentClassName="border-t border-white/5 px-4 py-3"
                  >
                    <p className="text-sm text-space-300">{llmReport.brief.suggestions_and_requests}</p>
                  </CollapsibleSection>
                  <CollapsibleSection
                    className="rounded-lg border border-white/10 bg-space-950/30 overflow-hidden"
                    title={<span className="text-amber-400">Complaints / criticism</span>}
                    defaultOpen
                    compact
                    contentClassName="border-t border-white/5 px-4 py-3"
                  >
                    <p className="text-sm text-space-300">{llmReport.brief.complaints_and_criticism}</p>
                  </CollapsibleSection>
                </div>
                <CollapsibleSection
                  className="rounded-lg border border-white/10 bg-space-950/30 overflow-hidden"
                  title={<span className="text-neon-purple">Agreements / disagreements</span>}
                  defaultOpen
                  compact
                  contentClassName="border-t border-white/5 px-4 py-3"
                >
                  <p className="text-sm text-space-300">{llmReport.brief.agreements_and_disagreements}</p>
                </CollapsibleSection>
                {llmReport.brief.notable_quotes.length > 0 ? (
                  <CollapsibleSection
                    className="rounded-lg border border-white/10 bg-space-950/30 overflow-hidden"
                    title={<span className="text-space-200">Notable excerpts</span>}
                    defaultOpen
                    compact
                    contentClassName="border-t border-white/5 px-4 py-3"
                  >
                    <ul className="list-disc pl-5 text-sm italic text-space-400">
                      {llmReport.brief.notable_quotes.map((q, i) => (
                        <li key={`${i}-${q.slice(0, 24)}`}>{q}</li>
                      ))}
                    </ul>
                  </CollapsibleSection>
                ) : null}
                {llmReport.brief.caveats.length > 0 ? (
                  <CollapsibleSection
                    className="rounded-lg border border-white/10 bg-space-950/30 overflow-hidden"
                    title={<span className="text-rose-300">Caveats</span>}
                    defaultOpen
                    compact
                    contentClassName="border-t border-white/5 px-4 py-3"
                  >
                    <ul className="list-disc pl-5 text-sm text-space-400">
                      {llmReport.brief.caveats.map((c, i) => (
                        <li key={`${i}-${c.slice(0, 24)}`}>{c}</li>
                      ))}
                    </ul>
                  </CollapsibleSection>
                ) : null}
              </div>
            ) : null}
          </CollapsibleSection>
        </motion.div>
      ) : null}
    </div>
  )
}

export default AnalyticsView
