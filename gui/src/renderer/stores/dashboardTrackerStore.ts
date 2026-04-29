import { create } from 'zustand'
import type { DashboardTrackers } from '../../shared/dashboardTrackers'
import { DASHBOARD_TRACKERS_SCHEMA_VERSION } from '../../shared/dashboardTrackers'

type DashboardTrackerState = DashboardTrackers & {
  hydrate: () => Promise<void>
  replaceFromMain: (next: DashboardTrackers) => void
}

const initialSnapshot: DashboardTrackers = {
  schemaVersion: DASHBOARD_TRACKERS_SCHEMA_VERSION,
  scrapesStarted: 0,
  commentsScraped: 0,
  totalStorageBytes: 0,
  updatedAt: '',
}

export const useDashboardTrackerStore = create<DashboardTrackerState>((set) => ({
  ...initialSnapshot,

  hydrate: async () => {
    if (typeof window === 'undefined' || !window.electronAPI?.dashboardTrackersRefreshStorage) {
      return
    }
    try {
      const next = await window.electronAPI.dashboardTrackersRefreshStorage()
      set({ ...next })
    } catch {
      try {
        if (window.electronAPI?.dashboardTrackersGet) {
          const fallback = await window.electronAPI.dashboardTrackersGet()
          set({ ...fallback })
        }
      } catch {
        /* keep defaults */
      }
    }
  },

  replaceFromMain: (next) => set({ ...next }),
}))
