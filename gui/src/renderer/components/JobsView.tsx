import React, { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Play,
  Pause,
  X,
  FolderOpen,
  Clock,
  CheckCircle,
  AlertCircle,
  Terminal,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Trash2,
  Loader2,
  Check,
  XCircle,
} from 'lucide-react'
import {
  useScrapeStore,
  ScrapeJob,
  hydrateScrapeJobsFromStore,
  parseJobWarnings,
  LogEntry,
  formatJobLaunchHeading,
} from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'
import { jobIdUsesProgressWebSocket } from '../constants/jobPrefixes'
import {
  extractYoutubeVideoId,
  fallbackYoutubeListTitle,
  fetchYoutubeOembedDisplay,
  outputFolderBasenameAsVideoId,
} from '../utils/youtubeDisplayMeta'

function formatJobDurationMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) {
    return '—'
  }
  const sec = Math.floor(ms / 1000)
  if (sec < 60) {
    return `${sec}s`
  }
  const min = Math.floor(sec / 60)
  const rSec = sec % 60
  if (min < 60) {
    return `${min}m ${String(rSec).padStart(2, '0')}s`
  }
  const hr = Math.floor(min / 60)
  const rMin = min % 60
  return `${hr}h ${String(rMin).padStart(2, '0')}m ${String(rSec).padStart(2, '0')}s`
}

const JobRuntimeLabel: React.FC<{ job: ScrapeJob; className?: string }> = ({ job, className }) => {
  const [tick, setTick] = useState(0)
  const isRunning = job.status === 'running'
  useEffect(() => {
    if (!isRunning || !job.startedAt) {
      return undefined
    }
    const id = window.setInterval(() => setTick((t) => t + 1), 1000)
    return () => window.clearInterval(id)
  }, [isRunning, job.startedAt])

  const line = useMemo(() => {
    if (!job.startedAt) {
      return null
    }
    const t0 = new Date(job.startedAt).getTime()
    if (!Number.isFinite(t0)) {
      return null
    }
    let t1: number
    if (isRunning) {
      t1 = Date.now()
    } else if (job.completedAt) {
      t1 = new Date(job.completedAt).getTime()
    } else if (job.logs.length > 0) {
      const last = job.logs[job.logs.length - 1]
      t1 = last ? new Date(last.timestamp).getTime() : Date.now()
    } else {
      t1 = Date.now()
    }
    if (!Number.isFinite(t1)) {
      return null
    }
    const ms = Math.max(0, t1 - t0)
    const label = isRunning ? 'Runtime' : 'Duration'
    return `${label} ${formatJobDurationMs(ms)}`
  }, [job.startedAt, job.completedAt, job.logs, isRunning, tick])

  if (!line) {
    return null
  }
  return (
    <span
      className={className ?? 'text-xs text-space-500 tabular-nums'}
      title="Wall time from job start until finish (or live if still running)"
    >
      {line}
    </span>
  )
}

const JobsView: React.FC = () => {
  const {
    jobs,
    activeJobId,
    pendingAutoExpandJobId,
    setActiveJob,
    setPendingAutoExpandJobId,
    removeJob,
    updateJob,
    addJobLog,
    clearFinishedJobs,
  } = useScrapeStore()
  const { serverUrl, isServerRunning } = useAppStore()
  const [expandedJob, setExpandedJob] = useState<string | null>(null)
  const [websockets, setWebsockets] = useState<Map<string, WebSocket>>(new Map())

  useEffect(() => {
    if (!pendingAutoExpandJobId) {
      return
    }
    if (!jobs.some((j) => j.id === pendingAutoExpandJobId)) {
      return
    }
    setExpandedJob(pendingAutoExpandJobId)
    setPendingAutoExpandJobId(null)
  }, [pendingAutoExpandJobId, jobs, setPendingAutoExpandJobId])

  // Connect to WebSocket for each running job
  useEffect(() => {
    if (!serverUrl || !isServerRunning) return

    jobs.forEach((job) => {
      if (job.status === 'running' && jobIdUsesProgressWebSocket(job.id) && !websockets.has(job.id)) {
        const ws = new WebSocket(`${serverUrl.replace('http', 'ws')}/ws/progress/${job.id}`)
        
        ws.onmessage = (event) => {
          const data = JSON.parse(event.data)

          if (data.progress !== undefined) {
            updateJob(job.id, { progress: data.progress })
          }

          if (data.status) {
            const details = (data.details && typeof data.details === 'object' ? data.details : {}) as Record<
              string,
              unknown
            >
            const patch: Partial<ScrapeJob> = {
              status: data.status,
              outputDir:
                typeof details.output_dir === 'string' ? details.output_dir : job.outputDir,
              error: typeof details.error === 'string' ? details.error : job.error,
            }
            if (data.status === 'completed') {
              patch.completedAt = new Date().toISOString()
              patch.warnings = parseJobWarnings(details.warnings)
            } else if (data.status === 'failed' || data.status === 'cancelled') {
              patch.completedAt = new Date().toISOString()
            }
            updateJob(job.id, patch)
          }

          if (data.log) {
            const lg = data.log as Record<string, unknown>
            const stepRaw = lg.step
            let step: LogEntry['step'] | undefined
            if (stepRaw && typeof stepRaw === 'object') {
              const ps = stepRaw as Record<string, unknown>
              const id = ps.id
              const phase = ps.phase
              if (
                typeof id === 'string' &&
                (phase === 'running' || phase === 'done' || phase === 'error')
              ) {
                step = { id, phase }
              }
            }
            addJobLog(job.id, {
              level: lg.level as LogEntry['level'],
              message: String(lg.message ?? ''),
              timestamp: (typeof lg.timestamp === 'string' ? lg.timestamp : null) || new Date().toISOString(),
              step,
            })
          }
        }

        ws.onclose = () => {
          setWebsockets((prev) => {
            const next = new Map(prev)
            next.delete(job.id)
            return next
          })
        }

        setWebsockets((prev) => {
          const next = new Map(prev)
          next.set(job.id, ws)
          return next
        })
      }
    })

    // Cleanup WebSockets for completed jobs
    websockets.forEach((ws, jobId) => {
      const job = jobs.find((j) => j.id === jobId)
      if (job && ['completed', 'failed', 'cancelled'].includes(job.status)) {
        ws.close()
      }
    })

    return () => {
      websockets.forEach((ws) => ws.close())
    }
  }, [jobs, serverUrl, isServerRunning])

  const handleCancel = async (jobId: string) => {
    if (!serverUrl) return
    
    try {
      const response = await fetch(`${serverUrl}/jobs/${jobId}/cancel`, { method: 'POST' })
      if (response.ok) {
        updateJob(jobId, { status: 'cancelled', completedAt: new Date().toISOString() })
      }
    } catch (error) {
      console.error('Failed to cancel job:', error)
    }
  }

  const handleOpenOutput = (outputDir?: string) => {
    if (outputDir) {
      window.electronAPI.openPath(outputDir)
    }
  }

  const sortedJobs = [...jobs].sort((a, b) => {
    const dateA = a.startedAt ? new Date(a.startedAt).getTime() : 0
    const dateB = b.startedAt ? new Date(b.startedAt).getTime() : 0
    return dateB - dateA
  })

  const handleRefreshJobs = () => {
    hydrateScrapeJobsFromStore({ mergeSession: true })
  }

  const hasFinishedJobs = jobs.some(
    (j) => j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled'
  )

  const handleClearFinishedJobs = () => {
    clearFinishedJobs()
    const remainingIds = new Set(useScrapeStore.getState().jobs.map((j) => j.id))
    setExpandedJob((id) => (id && remainingIds.has(id) ? id : null))
  }

  /** Stable key so we only re-fetch when jobs missing titles change (avoids IPC spam). */
  const jobsPendingTitleKey = useMemo(() => {
    return jobs
      .filter((j) => Boolean(j.outputDir) && !j.videoTitle)
      .map((j) => `${j.id}:${j.outputDir}`)
      .sort()
      .join('|')
  }, [jobs])

  useEffect(() => {
    if (!jobsPendingTitleKey || !window.electronAPI?.readOutputVideoMeta) {
      return
    }
    const snapshot = useScrapeStore.getState().jobs
    let cancelled = false
    const timers: ReturnType<typeof setTimeout>[] = []
    const byDir = new Map<string, string[]>()
    const urlByDir = new Map<string, string>()
    for (const job of snapshot) {
      if (!job.outputDir || job.videoTitle) {
        continue
      }
      const ids = byDir.get(job.outputDir) ?? []
      ids.push(job.id)
      byDir.set(job.outputDir, ids)
      if (job.url && !urlByDir.has(job.outputDir)) {
        urlByDir.set(job.outputDir, job.url)
      }
    }

    const enrichTitle = async (
      diskTitle: string,
      jobUrl: string,
      outputDir: string
    ): Promise<string> => {
      const t = diskTitle.trim()
      if (t) {
        return t
      }
      const vid =
        extractYoutubeVideoId(jobUrl) || outputFolderBasenameAsVideoId(outputDir) || ''
      if (vid) {
        const o = await fetchYoutubeOembedDisplay(vid)
        if (o?.title?.trim()) {
          return o.title.trim()
        }
        return fallbackYoutubeListTitle(vid)
      }
      return fallbackYoutubeListTitle(null)
    }

    void Promise.all(
      [...byDir.entries()].map(async ([dir, ids]) => {
        const jobUrl = urlByDir.get(dir) ?? ''
        const apply = (title: string | null | undefined) => {
          const t = title?.trim()
          if (!t || cancelled) {
            return
          }
          ids.forEach((jobId) => updateJob(jobId, { videoTitle: t }))
        }
        try {
          const meta = (await window.electronAPI.readOutputVideoMeta(dir)) as {
            title: string | null
            videoId: string | null
          } | null
          const diskTitle = meta?.title ?? ''
          const finalTitle = await enrichTitle(
            diskTitle,
            meta?.videoId ? `https://www.youtube.com/watch?v=${meta.videoId}` : jobUrl,
            dir
          )
          apply(finalTitle)
          if (!diskTitle.trim() && !cancelled) {
            timers.push(
              setTimeout(async () => {
                if (cancelled) {
                  return
                }
                try {
                  const retry = (await window.electronAPI.readOutputVideoMeta(dir)) as {
                    title: string | null
                    videoId: string | null
                  } | null
                  const retryDisk = retry?.title ?? ''
                  const next = await enrichTitle(
                    retryDisk,
                    retry?.videoId ? `https://www.youtube.com/watch?v=${retry.videoId}` : jobUrl,
                    dir
                  )
                  apply(next)
                } catch {
                  /* ignore */
                }
              }, 750)
            )
          }
        } catch {
          if (!cancelled) {
            const vid = extractYoutubeVideoId(jobUrl) || outputFolderBasenameAsVideoId(dir)
            apply(
              vid ? (await fetchYoutubeOembedDisplay(vid))?.title?.trim() || fallbackYoutubeListTitle(vid) : fallbackYoutubeListTitle(null)
            )
          }
        }
      })
    )

    return () => {
      cancelled = true
      timers.forEach(clearTimeout)
    }
  }, [jobsPendingTitleKey, updateJob])

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-display font-bold text-white">Scrape Jobs</h2>
          <p className="text-space-400">Track and manage your scraping jobs</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleRefreshJobs}
            className="futuristic-btn flex items-center gap-2 border border-white/10"
            title="Reload jobs from storage and scan output folders"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          <button
            type="button"
            onClick={handleClearFinishedJobs}
            disabled={!hasFinishedJobs}
            className="futuristic-btn flex items-center gap-2 border border-rose-500/30 text-rose-200 hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-40"
            title="Remove completed, failed, and cancelled jobs from the list (running and pending stay)"
          >
            <Trash2 className="w-4 h-4" />
            Clear
          </button>
          <span className="px-3 py-1 rounded-full bg-neon-blue/10 text-neon-blue text-sm">
            {jobs.filter((j) => j.status === 'running').length} Running
          </span>
          <span className="px-3 py-1 rounded-full bg-neon-green/10 text-neon-green text-sm">
            {jobs.filter((j) => j.status === 'completed').length} Completed
          </span>
        </div>
      </div>

      {sortedJobs.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <div className="w-20 h-20 rounded-full bg-space-800 flex items-center justify-center mx-auto mb-4">
            <Clock className="w-10 h-10 text-space-400" />
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">No Jobs Yet</h3>
          <p className="text-space-400">Start a new scrape to see jobs here</p>
        </div>
      ) : (
        <div className="space-y-3">
          {sortedJobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              isExpanded={expandedJob === job.id}
              isActive={activeJobId === job.id}
              onToggleExpand={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
              onSetActive={() => setActiveJob(job.id)}
              onCancel={() => handleCancel(job.id)}
              onRemove={() => removeJob(job.id)}
              onOpenOutput={() => handleOpenOutput(job.outputDir)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface JobCardProps {
  job: ScrapeJob
  isExpanded: boolean
  isActive: boolean
  onToggleExpand: () => void
  onSetActive: () => void
  onCancel: () => void
  onRemove: () => void
  onOpenOutput: () => void
}

const JobCard: React.FC<JobCardProps> = ({
  job,
  isExpanded,
  isActive,
  onToggleExpand,
  onSetActive: _onSetActive,
  onCancel,
  onRemove,
  onOpenOutput,
}) => {
  const statusConfig = {
    pending: { color: 'amber', icon: Clock, label: 'Pending' },
    running: { color: 'blue', icon: Play, label: 'Running' },
    completed: { color: 'green', icon: CheckCircle, label: 'Completed' },
    failed: { color: 'rose', icon: AlertCircle, label: 'Failed' },
    cancelled: { color: 'gray', icon: X, label: 'Cancelled' },
  }

  const status = statusConfig[job.status]
  const StatusIcon = status.icon

  return (
    <motion.div
      layout
      className={`
        glass-card overflow-hidden transition-all
        ${isActive ? 'border-neon-blue/40' : ''}
      `}
    >
      <div
        className="p-4 flex items-center gap-4 cursor-pointer"
        onClick={onToggleExpand}
      >
        {/* Status indicator */}
        <div className={`w-10 h-10 rounded-xl bg-${status.color}-500/10 flex items-center justify-center`}>
          <StatusIcon className={`w-5 h-5 text-${status.color}-500`} />
        </div>

        {/* Job info */}
        <div className="flex-1 min-w-0">
          <p
            className="text-white font-medium truncate"
            title={formatJobLaunchHeading(job)}
          >
            {formatJobLaunchHeading(job)}
          </p>
          <p
            className="text-sm text-space-300 truncate mt-0.5"
            title={job.videoTitle || (job.outputDir ? 'Resolving title…' : '') || job.url}
          >
            {job.videoTitle
              ? job.videoTitle
              : job.outputDir
                ? 'Resolving title…'
                : '—'}
          </p>
          <p
            className="text-xs text-space-500 truncate mt-0.5"
            title={job.url}
          >
            {job.url}
          </p>
          <div className="flex items-center gap-3 text-sm text-space-400 mt-1">
            <span>{job.type}</span>
            <span>•</span>
            <span>{status.label}</span>
            {job.startedAt && (
              <>
                <span>•</span>
                <span>{new Date(job.startedAt).toLocaleString()}</span>
                <span>•</span>
                <JobRuntimeLabel job={job} />
              </>
            )}
          </div>
        </div>

        {/* Progress */}
        {job.status === 'running' && (
          <div className="w-40 sm:w-48 shrink-0">
            <div className="flex items-center justify-between text-sm mb-1.5">
              <span className="text-space-400">Progress</span>
              <span className="text-white tabular-nums">{job.progress}%</span>
            </div>
            <div className="progress-bar progress-bar--active h-3.5 md:h-4 rounded-md">
              <div
                className="progress-bar-fill progress-bar-fill--striped h-full rounded-md"
                style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }}
              />
            </div>
            {job.startedAt ? (
              <div className="mt-1 text-right">
                <JobRuntimeLabel job={job} />
              </div>
            ) : null}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2">
          {job.status === 'running' && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onCancel()
              }}
              className="p-2 rounded-lg hover:bg-rose-500/10 text-space-400 hover:text-rose-400 transition-colors"
              title="Cancel job"
            >
              <Pause className="w-4 h-4" />
            </button>
          )}
          
          {job.outputDir && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onOpenOutput()
              }}
              className="p-2 rounded-lg hover:bg-white/10 text-space-400 hover:text-white transition-colors"
              title="Open output folder"
            >
              <FolderOpen className="w-4 h-4" />
            </button>
          )}
          
          <button
            onClick={(e) => {
              e.stopPropagation()
              onRemove()
            }}
            className="p-2 rounded-lg hover:bg-rose-500/10 text-space-400 hover:text-rose-400 transition-colors"
            title="Remove job"
          >
            <X className="w-4 h-4" />
          </button>

          <button className="p-2 text-space-400">
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Expanded details */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-glass-border"
          >
            <div className="p-4 space-y-4">
              {/* Job details */}
              <div className="flex flex-col gap-4 text-sm sm:flex-row sm:items-start sm:gap-6">
                <div className="shrink-0 sm:max-w-[11rem]">
                  <p className="mb-1 text-space-400">Job ID</p>
                  <p className="font-mono text-white">{job.id}</p>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="mb-1 text-space-400">Output Directory</p>
                  <p className="break-all font-mono text-xs leading-relaxed text-white">{job.outputDir || 'N/A'}</p>
                </div>
                <div className="shrink-0 sm:w-28 sm:text-right">
                  <p className="mb-1 text-space-400">Wall time</p>
                  <p className="text-white tabular-nums text-sm">
                    {job.startedAt ? <JobRuntimeLabel job={job} className="text-white tabular-nums text-sm" /> : '—'}
                  </p>
                </div>
                <div className="shrink-0 sm:w-24 sm:text-right">
                  <p className="mb-1 text-space-400">Progress</p>
                  <p className="text-white">{job.progress}%</p>
                </div>
              </div>

              {job.warnings && job.warnings.length > 0 && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-100/90">
                  <p className="font-medium text-amber-200/95 mb-1">Some steps could not finish</p>
                  <ul className="list-disc list-inside space-y-1 text-xs text-amber-100/80">
                    {job.warnings.map((w) => (
                      <li key={w.operation}>
                        <span className="font-medium text-amber-200/90">
                          {STEP_LABELS[w.operation] ?? w.operation}
                        </span>
                        {' — '}
                        {w.error}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Logs */}
              {job.logs.length > 0 && (
                <div>
                  <p className="text-sm text-space-400 mb-2 flex items-center gap-2">
                    <Terminal className="w-4 h-4" />
                    Logs ({job.logs.length} entries)
                  </p>
                  <div className="code-block p-3 max-h-48 overflow-auto space-y-1">
                    {buildCollapsedStepLogs(job.logs).map((row, index) => (
                      <LogLineRow key={`${row.kind}-${index}`} row={row} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

const STEP_LABELS: Record<string, string> = {
  video: 'Video details',
  thumbnails: 'Thumbnails',
  transcript: 'Transcript',
  comments: 'Comments',
  download: 'Download',
}

type CollapsedLogRow =
  | { kind: 'plain'; log: LogEntry }
  | { kind: 'step'; log: LogEntry }

/** One row per step id — latest websocket message replaces the line (spinner → check/error). */
function buildCollapsedStepLogs(logs: LogEntry[]): CollapsedLogRow[] {
  const out: CollapsedLogRow[] = []
  const indexByStepId = new Map<string, number>()
  for (const log of logs) {
    const sid = log.step?.id
    if (sid) {
      const existing = indexByStepId.get(sid)
      if (existing !== undefined) {
        out[existing] = { kind: 'step', log }
      } else {
        indexByStepId.set(sid, out.length)
        out.push({ kind: 'step', log })
      }
    } else {
      out.push({ kind: 'plain', log })
    }
  }
  return out
}

const LogLineRow: React.FC<{ row: CollapsedLogRow }> = ({ row }) => {
  const log = row.log
  const phase = log.step?.phase

  const endIcon =
    row.kind === 'step' ? (
      phase === 'running' ? (
        <Loader2 className="w-3.5 h-3.5 shrink-0 text-neon-blue animate-spin" aria-hidden />
      ) : phase === 'done' ? (
        <Check className="w-3.5 h-3.5 shrink-0 text-emerald-400" aria-hidden />
      ) : phase === 'error' ? (
        <XCircle className="w-3.5 h-3.5 shrink-0 text-rose-400" aria-hidden />
      ) : null
    ) : null

  return (
    <div className="flex gap-2 text-xs items-start">
      <span className="text-space-500 shrink-0">{new Date(log.timestamp).toLocaleTimeString()}</span>
      <span
        className={`
          font-medium uppercase shrink-0
          ${log.level === 'error' ? 'text-rose-400' :
            log.level === 'warn' ? 'text-amber-400' :
            log.level === 'info' ? 'text-neon-blue' : 'text-space-400'}
        `}
      >
        {log.level}
      </span>
      <span className="text-space-300 flex-1 min-w-0 break-words">{log.message}</span>
      {endIcon ? <span className="shrink-0 pt-0.5">{endIcon}</span> : <span className="w-3.5 shrink-0" />}
    </div>
  )
}

export default JobsView
