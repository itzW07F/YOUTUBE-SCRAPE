import { create } from 'zustand'
import type { DashboardTrackerIncrements } from '../../shared/dashboardTrackers'

const MAX_PERSISTED_LOGS_PER_JOB = 150

/** Persisted dirs user removed so filesystem discovery cannot recreate those cards after Clear/Refresh. */
export const SCRAPE_STORE_KEY_DISMISS = 'scrapeDismissedDirs'

/** Set true after hydrateScrapeJobsFromStore finishes (or no-op) so we do not persist empty jobs over stored history. */
export let scrapePersistenceReady = false

export interface JobStepWarning {
  operation: string
  error: string
}

export interface LogEntry {
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
  timestamp: string
  /** When set, GUI may collapse updates for the same id (spinner → done/error). */
  step?: {
    id: string
    phase: 'running' | 'done' | 'error'
  }
}

export interface ScrapeJob {
  id: string
  url: string
  /** From output video.json via IPC; optional so older persisted jobs still load. */
  videoTitle?: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  type: 'video' | 'comments' | 'transcript' | 'thumbnails' | 'download' | 'all'
  operations?: Array<'video' | 'comments' | 'transcript' | 'thumbnails' | 'download'>
  outputDir?: string
  error?: string
  /** Steps that failed while other operations continued (API `warnings`). */
  warnings?: JobStepWarning[]
  result?: unknown
  startedAt?: string
  completedAt?: string
  logs: LogEntry[]
}

/** Dashboard quick-action presets: exactly one flag true, or `all` for every option. */
export type ScrapeQuickPreset =
  | 'video'
  | 'comments'
  | 'transcript'
  | 'thumbnails'
  | 'download'
  | 'all'

type ScrapeOptionsBase = {
  includeVideo: boolean
  includeComments: boolean
  includeTranscript: boolean
  includeThumbnails: boolean
  includeDownload: boolean
  maxComments: number
  transcriptFormat: 'txt' | 'vtt' | 'json'
  videoQuality: string
}

function scrapePresetToIncludes(
  preset: ScrapeQuickPreset
): Pick<ScrapeOptionsBase, 'includeVideo' | 'includeComments' | 'includeTranscript' | 'includeThumbnails' | 'includeDownload'> {
  const off = {
    includeVideo: false,
    includeComments: false,
    includeTranscript: false,
    includeThumbnails: false,
    includeDownload: false,
  }
  switch (preset) {
    case 'video':
      return { ...off, includeVideo: true }
    case 'comments':
      return { ...off, includeComments: true }
    case 'transcript':
      return { ...off, includeTranscript: true }
    case 'thumbnails':
      return { ...off, includeThumbnails: true }
    case 'download':
      return { ...off, includeDownload: true }
    case 'all':
      return {
        includeVideo: true,
        includeComments: true,
        includeTranscript: true,
        includeThumbnails: true,
        includeDownload: true,
      }
    default:
      return { ...off, includeVideo: true }
  }
}

interface ScrapeState {
  jobs: ScrapeJob[]
  activeJobId: string | null
  scrapeOptions: {
    includeVideo: boolean
    includeComments: boolean
    includeTranscript: boolean
    includeThumbnails: boolean
    includeDownload: boolean
    maxComments: number
    transcriptFormat: 'txt' | 'vtt' | 'json'
    videoQuality: string
  }
  addJob: (job: Omit<ScrapeJob, 'logs'>) => void
  updateJob: (id: string, updates: Partial<ScrapeJob>) => void
  addJobLog: (id: string, log: LogEntry) => void
  removeJob: (id: string) => void
  removeJobsByOutputDir: (outputDir: string) => void
  /** Remove completed / failed / cancelled jobs; keeps pending and running. */
  clearFinishedJobs: () => void
  setActiveJob: (id: string | null) => void
  updateScrapeOptions: (options: Partial<ScrapeState['scrapeOptions']>) => void
  /** Sets exactly one scrape target (or all); used by dashboard Quick Actions. */
  applyScrapePreset: (preset: ScrapeQuickPreset) => void
}

export interface DiscoveredScrapeOutput {
  outputDir: string
  videoId: string
  url: string
  completedAt: string
}

/** Normalize output paths for dismissal / dedupe comparisons (POSIX slashes, trimmed). */
export function canonicalOutputDirPath(p: string | undefined): string | null {
  if (p == null || typeof p !== 'string') {
    return null
  }
  const t = p.trim()
  if (!t) {
    return null
  }
  return t.replace(/\\/g, '/').replace(/\/+$/, '')
}

export async function appendDismissedOutputDirs(paths: Array<string | undefined>): Promise<void> {
  if (typeof window === 'undefined' || !window.electronAPI) {
    return
  }
  const canon = [...new Set(paths.map(canonicalOutputDirPath).filter((x): x is string => Boolean(x)))]
  if (!canon.length) {
    return
  }
  const prevRaw = await window.electronAPI.storeGet(SCRAPE_STORE_KEY_DISMISS)
  const prevList = Array.isArray(prevRaw)
    ? prevRaw.filter((x): x is string => typeof x === 'string')
    : []
  const prevCanon = [...new Set(prevList.map(canonicalOutputDirPath).filter((x): x is string => Boolean(x)))]
  const merged = [...new Set([...prevCanon, ...canon])].slice(-500)
  await window.electronAPI.storeSet(SCRAPE_STORE_KEY_DISMISS, merged)
}

function mergePreferSessionLogs(diskRow: ScrapeJob, session: ScrapeJob): ScrapeJob {
  const logs = session.logs.length >= diskRow.logs.length ? session.logs : diskRow.logs
  return {
    ...diskRow,
    ...session,
    logs,
    warnings: session.warnings ?? diskRow.warnings,
  }
}

export function mergeJobsPreferSessionLogs(fromDiskMerge: ScrapeJob[], session: ScrapeJob[]): ScrapeJob[] {
  if (!session.length) {
    return fromDiskMerge
  }
  const map = new Map<string, ScrapeJob>()
  for (const j of fromDiskMerge) {
    map.set(j.id, j)
  }
  for (const s of session) {
    const ex = map.get(s.id)
    if (!ex) {
      map.set(s.id, s)
      continue
    }
    map.set(s.id, mergePreferSessionLogs(ex, s))
  }
  const out = [...map.values()].sort((a, b) => {
    const ta = a.completedAt || a.startedAt || ''
    const tb = b.completedAt || b.startedAt || ''
    return tb.localeCompare(ta)
  })
  return out
}

export function parseJobWarnings(raw: unknown): JobStepWarning[] | undefined {
  if (!Array.isArray(raw) || raw.length === 0) {
    return undefined
  }
  const out: JobStepWarning[] = []
  for (const item of raw) {
    if (item && typeof item === 'object') {
      const o = item as Record<string, unknown>
      if (typeof o.operation === 'string' && typeof o.error === 'string') {
        out.push({ operation: o.operation, error: o.error })
      }
    }
  }
  return out.length > 0 ? out : undefined
}

function sanitizeJob(input: unknown): ScrapeJob | null {
  if (input == null || typeof input !== 'object') {
    return null
  }
  const j = input as Record<string, unknown>
  if (typeof j.id !== 'string' || typeof j.url !== 'string') {
    return null
  }
  const status = j.status
  const allowed: ScrapeJob['status'][] = ['pending', 'running', 'completed', 'failed', 'cancelled']
  return {
    id: j.id,
    url: j.url,
    status: allowed.includes(status as ScrapeJob['status']) ? (status as ScrapeJob['status']) : 'completed',
    progress: typeof j.progress === 'number' ? j.progress : 0,
    type:
      j.type === 'video' ||
      j.type === 'comments' ||
      j.type === 'transcript' ||
      j.type === 'thumbnails' ||
      j.type === 'download' ||
      j.type === 'all'
        ? j.type
        : 'all',
    videoTitle: typeof j.videoTitle === 'string' ? j.videoTitle : undefined,
    outputDir: typeof j.outputDir === 'string' ? j.outputDir : undefined,
    operations: Array.isArray(j.operations)
      ? j.operations.filter(
          (operation): operation is NonNullable<ScrapeJob['operations']>[number] =>
            operation === 'video' ||
            operation === 'comments' ||
            operation === 'transcript' ||
            operation === 'thumbnails' ||
            operation === 'download'
        )
      : undefined,
    error: typeof j.error === 'string' ? j.error : undefined,
    warnings: parseJobWarnings(j.warnings),
    result: j.result,
    startedAt: typeof j.startedAt === 'string' ? j.startedAt : undefined,
    completedAt: typeof j.completedAt === 'string' ? j.completedAt : undefined,
    logs: Array.isArray(j.logs) ? (j.logs as ScrapeJob['logs']) : [],
  }
}

/**
 * Merges electron-store job history with on-disk output folders (video.json) from a discover pass after restart.
 */
export function mergeScrapeJobsOnHydration(
  persisted: unknown,
  discovered: DiscoveredScrapeOutput[],
  dismissedDirs: ReadonlySet<string>,
  mergeSessionJobs?: ScrapeJob[]
): ScrapeJob[] {
  const rawList = Array.isArray(persisted) ? persisted : []
  const list: ScrapeJob[] = []
  for (const item of rawList) {
    const s = sanitizeJob(item)
    if (s) {
      list.push(s)
    }
  }
  const dirsOccupied = new Set(
    list.map((j) => canonicalOutputDirPath(j.outputDir ?? undefined)).filter((d): d is string => Boolean(d))
  )
  for (const d of discovered) {
    const dir = d.outputDir
    const canon = canonicalOutputDirPath(dir ?? undefined)
    if (!canon || dismissedDirs.has(canon)) {
      continue
    }
    if (dirsOccupied.has(canon)) {
      continue
    }
    dirsOccupied.add(canon)
    const short = d.videoId.replace(/[^a-zA-Z0-9_-]/g, '').slice(-12) || 'job'
    list.push({
      id: `fs-${short}-${String(dir).slice(-8)}`,
      url: d.url,
      status: 'completed',
      type: 'all',
      progress: 100,
      outputDir: dir,
      startedAt: d.completedAt,
      completedAt: d.completedAt,
      logs: [],
    })
  }
  list.sort((a, b) => {
    const tA = a.completedAt || a.startedAt || ''
    const tB = b.completedAt || b.startedAt || ''
    return tB.localeCompare(tA)
  })

  return mergeSessionJobs?.length ? mergeJobsPreferSessionLogs(list, mergeSessionJobs) : list
}

function dismissedDirsFromStored(raw: unknown): Set<string> {
  const xs = Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string') : []
  const can = [...new Set(xs.map(canonicalOutputDirPath).filter((x): x is string => Boolean(x)))]
  return new Set(can)
}

/** Options.mergeSessionJobs: keep in-memory logs when re-merging (used by Refresh). */
export function hydrateScrapeJobsFromStore(options?: { mergeSession?: boolean }): void {
  if (typeof window === 'undefined' || !window.electronAPI) {
    scrapePersistenceReady = true
    return
  }
  const api = window.electronAPI
  const mergeSession = options?.mergeSession ?? false
  void Promise.all([api.storeGet('scrapeJobs'), api.storeGet(SCRAPE_STORE_KEY_DISMISS), api.discoverScrapeOutputs()])
    .then(([raw, dismissedRaw, discovered]) => {
      const dismissed = dismissedDirsFromStored(dismissedRaw)
      const session = mergeSession ? useScrapeStore.getState().jobs : undefined
      const merged = mergeScrapeJobsOnHydration(raw, discovered, dismissed, session)
      scrapePersistenceReady = true
      useScrapeStore.setState({ jobs: merged })
    })
    .catch(() => {
      scrapePersistenceReady = true
    })
}

export function jobsForPersistence(jobs: ScrapeJob[]): ScrapeJob[] {
  return jobs.map((j) => ({
    ...j,
    logs: j.logs.slice(-MAX_PERSISTED_LOGS_PER_JOB),
  }))
}

export const useScrapeStore = create<ScrapeState>((set, get) => ({
  jobs: [],
  activeJobId: null,
  scrapeOptions: {
    includeVideo: true,
    includeComments: false,
    includeTranscript: false,
    includeThumbnails: false,
    includeDownload: false,
    maxComments: 100,
    transcriptFormat: 'txt',
    videoQuality: 'best',
  },

  addJob: (job) => {
    notifyDashboardIncrements({ scrapesStarted: 1 })
    set((state) => ({
      jobs: [{ ...job, logs: [] }, ...state.jobs],
    }))
  },

  updateJob: (id, updates) => {
    const prev = get().jobs.find((j) => j.id === id)
    const mergedOutputDir =
      typeof updates.outputDir === 'string' ? updates.outputDir : prev?.outputDir
    if (
      prev &&
      updates.status !== undefined &&
      updates.status !== prev.status &&
      updates.status === 'completed' &&
      mergedOutputDir &&
      typeof window !== 'undefined' &&
      window.electronAPI?.dashboardTrackersSyncAfterJob
    ) {
      void window.electronAPI.dashboardTrackersSyncAfterJob(mergedOutputDir)
    }
    set((state) => ({
      jobs: state.jobs.map((job) =>
        job.id === id ? { ...job, ...updates } : job
      ),
    }))
  },

  addJobLog: (id, log) => {
    set((state) => ({
      jobs: state.jobs.map((job) =>
        job.id === id
          ? { ...job, logs: [...job.logs, log] }
          : job
      ),
    }))
  },

  removeJob: (id) => {
    let dismissedPath: string | undefined
    set((state) => {
      const hit = state.jobs.find((j) => j.id === id)
      dismissedPath = hit?.outputDir
      return {
        jobs: state.jobs.filter((job) => job.id !== id),
      }
    })
    void appendDismissedOutputDirs(dismissedPath ? [dismissedPath] : [])
    persistScrapeJobsNow()
  },

  removeJobsByOutputDir: (outputDir) => {
    if (!outputDir) {
      return
    }
    set((state) => ({
      jobs: state.jobs.filter((job) => job.outputDir !== outputDir),
    }))
    void appendDismissedOutputDirs([outputDir])
    persistScrapeJobsNow()
  },

  clearFinishedJobs: () => {
    let toDismiss: string[] = []
    set((state) => {
      const removed = state.jobs.filter(
        (j) => j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled'
      )
      toDismiss = removed.map((j) => j.outputDir).filter((d): d is string => Boolean(d?.trim()))

      const next = state.jobs.filter((j) => j.status === 'pending' || j.status === 'running')
      const activeStill =
        state.activeJobId != null && next.some((j) => j.id === state.activeJobId)
      return {
        jobs: next,
        activeJobId: activeStill ? state.activeJobId : null,
      }
    })
    void appendDismissedOutputDirs(toDismiss)
    persistScrapeJobsNow()
  },

  setActiveJob: (id) => {
    set({ activeJobId: id })
  },

  updateScrapeOptions: (options) => {
    set((state) => ({
      scrapeOptions: { ...state.scrapeOptions, ...options },
    }))
  },

  applyScrapePreset: (preset) => {
    set((state) => ({
      scrapeOptions: {
        ...state.scrapeOptions,
        ...scrapePresetToIncludes(preset),
      },
    }))
  },
}))

/** Flush jobs to electron-store immediately (debounced saver may omit recent websocket logs otherwise). */
export function persistScrapeJobsNow(): void {
  if (!scrapePersistenceReady || typeof window === 'undefined' || !window.electronAPI) {
    return
  }
  void window.electronAPI.storeSet('scrapeJobs', jobsForPersistence(useScrapeStore.getState().jobs))
}

function notifyDashboardIncrements(inc: DashboardTrackerIncrements): void {
  if (typeof window === 'undefined' || !window.electronAPI?.dashboardTrackersApplyIncrements) {
    return
  }
  void window.electronAPI.dashboardTrackersApplyIncrements(inc)
}
