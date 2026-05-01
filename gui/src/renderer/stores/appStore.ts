import { create } from 'zustand'

export const UI_FONT_SIZE_MIN = 80
export const UI_FONT_SIZE_MAX = 140
export const UI_FONT_SIZE_DEFAULT = 100

function applyUiFontSizePercentToDom(percent: number): void {
  if (typeof document === 'undefined') {
    return
  }
  const p = Math.min(UI_FONT_SIZE_MAX, Math.max(UI_FONT_SIZE_MIN, percent))
  document.documentElement.style.setProperty('--app-font-scale', String(p / 100))
}

export const DOWNLOAD_MAX_CONCURRENT_DEFAULT = 2
export const DOWNLOAD_MAX_CONCURRENT_MIN = 1
export const DOWNLOAD_MAX_CONCURRENT_MAX = 16
export const FFMPEG_THREADS_DEFAULT = 0
export const FFMPEG_THREADS_MAX = 64

interface AppState {
  isServerRunning: boolean
  serverUrl: string | null
  isDarkMode: boolean
  outputDirectory: string
  uiFontSizePercent: number
  /** Concurrent scrape jobs allowed on the Python API (browser-heavy). */
  downloadMaxConcurrentJobs: number
  /** FFmpeg -threads for transcoding/remux (0 = omit, use FFmpeg default/auto). */
  ffmpegThreads: number
  checkServerStatus: () => Promise<void>
  setDarkMode: (isDark: boolean) => void
  setOutputDirectory: (path: string) => void
  setUiFontSizePercent: (percent: number) => void
  setDownloadMaxConcurrentJobs: (n: number) => void
  setFfmpegThreads: (n: number) => void
}

export const useAppStore = create<AppState>((set) => ({
  isServerRunning: false,
  serverUrl: null,
  isDarkMode: true,
  outputDirectory: '',
  uiFontSizePercent: UI_FONT_SIZE_DEFAULT,
  downloadMaxConcurrentJobs: DOWNLOAD_MAX_CONCURRENT_DEFAULT,
  ffmpegThreads: FFMPEG_THREADS_DEFAULT,

  checkServerStatus: async () => {
    if (typeof window === 'undefined' || !window.electronAPI) {
      return
    }
    try {
      const status = await window.electronAPI.getServerStatus()
      set({ 
        isServerRunning: status.running, 
        serverUrl: status.url || null 
      })
    } catch {
      set({ isServerRunning: false, serverUrl: null })
    }
  },

  setDarkMode: (isDark: boolean) => {
    set({ isDarkMode: isDark })
    const el = document.documentElement
    el.setAttribute('data-theme', isDark ? 'dark' : 'light')
    if (isDark) {
      el.classList.add('dark')
    } else {
      el.classList.remove('dark')
    }
    if (typeof window !== 'undefined' && window.electronAPI) {
      void window.electronAPI.storeSet('isDarkMode', isDark)
    }
  },

  setOutputDirectory: (path: string) => {
    set({ outputDirectory: path })
    if (typeof window !== 'undefined' && window.electronAPI) {
      void window.electronAPI.storeSet('outputDirectory', path)
    }
  },

  setUiFontSizePercent: (percent: number) => {
    const p = Math.min(UI_FONT_SIZE_MAX, Math.max(UI_FONT_SIZE_MIN, Math.round(percent)))
    set({ uiFontSizePercent: p })
    applyUiFontSizePercentToDom(p)
    if (typeof window !== 'undefined' && window.electronAPI) {
      void window.electronAPI.storeSet('uiFontSizePercent', p)
    }
  },

  setDownloadMaxConcurrentJobs: (n: number) => {
    const v = Math.min(
      DOWNLOAD_MAX_CONCURRENT_MAX,
      Math.max(DOWNLOAD_MAX_CONCURRENT_MIN, Math.round(Number(n)) || DOWNLOAD_MAX_CONCURRENT_DEFAULT)
    )
    set({ downloadMaxConcurrentJobs: v })
    if (typeof window !== 'undefined' && window.electronAPI) {
      void window.electronAPI.storeSet('downloadMaxConcurrentJobs', v)
    }
  },

  setFfmpegThreads: (n: number) => {
    const v = Math.min(FFMPEG_THREADS_MAX, Math.max(0, Math.round(Number(n)) || 0))
    set({ ffmpegThreads: v })
    if (typeof window !== 'undefined' && window.electronAPI) {
      void window.electronAPI.storeSet('ffmpegThreads', v)
    }
  },
}))

/** Call once from App mount; avoids throwing at module load if preload is missing. */
export function hydrateOutputDirectoryFromStore(): void {
  if (typeof window === 'undefined' || !window.electronAPI) {
    return
  }
  void window.electronAPI
    .storeGet('outputDirectory')
    .then((path) => {
      if (path) {
        useAppStore.setState({ outputDirectory: path as string })
      }
    })
    .catch(() => {
      // ignore
    })
}

/** Restores theme from electron-store and applies `data-theme` / body class. */
export function hydrateThemeFromStore(): void {
  if (typeof window === 'undefined' || !window.electronAPI) {
    return
  }
  void window.electronAPI
    .storeGet('isDarkMode')
    .then((v) => {
      const isDark = v === false ? false : v === true ? true : true
      useAppStore.getState().setDarkMode(isDark)
    })
    .catch(() => {
      useAppStore.getState().setDarkMode(true)
    })
}

/** Restores UI font size from electron-store and applies --app-font-scale on :root. */
export function hydrateUiFontSizeFromStore(): void {
  if (typeof window === 'undefined' || !window.electronAPI) {
    applyUiFontSizePercentToDom(UI_FONT_SIZE_DEFAULT)
    return
  }
  void window.electronAPI
    .storeGet('uiFontSizePercent')
    .then((v) => {
      const n = typeof v === 'number' ? v : typeof v === 'string' ? Number.parseInt(v, 10) : NaN
      const p =
        Number.isFinite(n) && n >= UI_FONT_SIZE_MIN && n <= UI_FONT_SIZE_MAX
          ? Math.round(n)
          : UI_FONT_SIZE_DEFAULT
      useAppStore.setState({ uiFontSizePercent: p })
      applyUiFontSizePercentToDom(p)
    })
    .catch(() => {
      applyUiFontSizePercentToDom(UI_FONT_SIZE_DEFAULT)
    })
}

/** Parallel scrape jobs + FFmpeg thread settings (Python process reads these on spawn via env). */
export function hydrateDownloadSpawnSettingsFromStore(): void {
  if (typeof window === 'undefined' || !window.electronAPI) {
    return
  }
  void Promise.all([
    window.electronAPI.storeGet('downloadMaxConcurrentJobs'),
    window.electronAPI.storeGet('ffmpegThreads'),
  ])
    .then(([jobs, threads]) => {
      const jc =
        typeof jobs === 'number'
          ? jobs
          : typeof jobs === 'string'
            ? Number.parseInt(jobs, 10)
            : Number.NaN
      const ft =
        typeof threads === 'number'
          ? threads
          : typeof threads === 'string'
            ? Number.parseInt(threads, 10)
            : Number.NaN
      useAppStore.setState({
        downloadMaxConcurrentJobs:
          Number.isFinite(jc) && jc >= DOWNLOAD_MAX_CONCURRENT_MIN && jc <= DOWNLOAD_MAX_CONCURRENT_MAX
            ? jc
            : DOWNLOAD_MAX_CONCURRENT_DEFAULT,
        ffmpegThreads:
          Number.isFinite(ft) && ft >= 0 && ft <= FFMPEG_THREADS_MAX ? ft : FFMPEG_THREADS_DEFAULT,
      })
    })
    .catch(() => {
      // ignore
    })
}
