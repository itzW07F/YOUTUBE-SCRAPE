/** Shared shape for `dashboard-trackers.json` (userData) and IPC payloads. */

export const DASHBOARD_TRACKERS_SCHEMA_VERSION = 2 as const

export interface DashboardTrackers {
  schemaVersion: typeof DASHBOARD_TRACKERS_SCHEMA_VERSION
  /** Jobs started from the New Scrape flow (lifetime). */
  scrapesStarted: number
  /** Sum of `total_count` from each completed job that produced `comments.json` (lifetime). */
  commentsScraped: number
  /** Total bytes under configured output roots (rescanned from disk). */
  totalStorageBytes: number
  updatedAt: string
}

/** Positive deltas applied atomically in the main process (sums into the JSON file). */
export interface DashboardTrackerIncrements {
  scrapesStarted?: number
  commentsScraped?: number
}
