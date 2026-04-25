import { create } from 'zustand'

const MAX_PERSISTED_LOGS_PER_JOB = 150

/** Set true after hydrateScrapeJobsFromStore finishes (or no-op) so we do not persist empty jobs over stored history. */
export let scrapePersistenceReady = false

export interface ScrapeJob {
  id: string
  url: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  type: 'video' | 'comments' | 'transcript' | 'thumbnails' | 'download' | 'all'
  operations?: Array<'video' | 'comments' | 'transcript' | 'thumbnails' | 'download'>
  outputDir?: string
  error?: string
  result?: unknown
  startedAt?: string
  completedAt?: string
  logs: LogEntry[]
}

interface LogEntry {
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
  timestamp: string
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
  setActiveJob: (id: string | null) => void
  updateScrapeOptions: (options: Partial<ScrapeState['scrapeOptions']>) => void
}

export interface DiscoveredScrapeOutput {
  outputDir: string
  videoId: string
  url: string
  completedAt: string
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
  discovered: DiscoveredScrapeOutput[]
): ScrapeJob[] {
  const rawList = Array.isArray(persisted) ? persisted : []
  const list: ScrapeJob[] = []
  for (const item of rawList) {
    const s = sanitizeJob(item)
    if (s) {
      list.push(s)
    }
  }
  const dirs = new Set(
    list.map((j) => j.outputDir).filter((d): d is string => Boolean(d && d.length > 0))
  )
  for (const d of discovered) {
    const dir = d.outputDir
    if (!dir || dirs.has(dir)) {
      continue
    }
    dirs.add(dir)
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
  return list
}

/** Call once on app mount; restores jobs from disk + discovers completed outputs. */
export function hydrateScrapeJobsFromStore(): void {
  if (typeof window === 'undefined' || !window.electronAPI) {
    scrapePersistenceReady = true
    return
  }
  const api = window.electronAPI
  void Promise.all([api.storeGet('scrapeJobs'), api.discoverScrapeOutputs()])
    .then(([raw, discovered]) => {
      const merged = mergeScrapeJobsOnHydration(raw, discovered)
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

export const useScrapeStore = create<ScrapeState>((set) => ({
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
    set((state) => ({
      jobs: [{ ...job, logs: [] }, ...state.jobs],
    }))
  },

  updateJob: (id, updates) => {
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
    set((state) => ({
      jobs: state.jobs.filter((job) => job.id !== id),
    }))
  },

  setActiveJob: (id) => {
    set({ activeJobId: id })
  },

  updateScrapeOptions: (options) => {
    set((state) => ({
      scrapeOptions: { ...state.scrapeOptions, ...options },
    }))
  },
}))
