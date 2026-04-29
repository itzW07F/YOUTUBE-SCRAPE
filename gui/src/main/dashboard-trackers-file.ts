import fs from 'node:fs'
import path from 'node:path'
import { app } from 'electron'
import type Store from 'electron-store'
import {
  DASHBOARD_TRACKERS_SCHEMA_VERSION,
  type DashboardTrackerIncrements,
  type DashboardTrackers,
} from '../shared/dashboardTrackers'
import { getAllowedOutputRoots, isOutputDirAllowed } from './media-serve'

export const DASHBOARD_TRACKERS_FILENAME = 'dashboard-trackers.json'

const MAX_TREE_DEPTH = 12

function trackersPath(): string {
  return path.join(app.getPath('userData'), DASHBOARD_TRACKERS_FILENAME)
}

function clampNonNegative(n: number): number {
  if (!Number.isFinite(n) || n < 0) {
    return 0
  }
  return Math.floor(n)
}

export function defaultDashboardTrackers(): DashboardTrackers {
  const now = new Date().toISOString()
  return {
    schemaVersion: DASHBOARD_TRACKERS_SCHEMA_VERSION,
    scrapesStarted: 0,
    commentsScraped: 0,
    totalStorageBytes: 0,
    updatedAt: now,
  }
}

function normalizeParsed(raw: unknown): DashboardTrackers {
  const d = defaultDashboardTrackers()
  if (raw == null || typeof raw !== 'object') {
    return d
  }
  const j = raw as Record<string, unknown>
  if (typeof j.scrapesStarted === 'number') {
    d.scrapesStarted = clampNonNegative(j.scrapesStarted)
  }
  if (typeof j.commentsScraped === 'number') {
    d.commentsScraped = clampNonNegative(j.commentsScraped)
  }
  if (typeof j.totalStorageBytes === 'number') {
    d.totalStorageBytes = clampNonNegative(j.totalStorageBytes)
  }
  if (typeof j.updatedAt === 'string') {
    d.updatedAt = j.updatedAt
  }
  return d
}

export function readDashboardTrackers(): DashboardTrackers {
  const p = trackersPath()
  try {
    if (!fs.existsSync(p)) {
      const initial = defaultDashboardTrackers()
      writeDashboardTrackers(initial)
      return initial
    }
    const rawText = fs.readFileSync(p, 'utf8')
    const parsed = JSON.parse(rawText) as unknown
    return normalizeParsed(parsed)
  } catch {
    return defaultDashboardTrackers()
  }
}

export function writeDashboardTrackers(data: DashboardTrackers): void {
  const p = trackersPath()
  const dir = path.dirname(p)
  fs.mkdirSync(dir, { recursive: true })
  data.updatedAt = new Date().toISOString()
  fs.writeFileSync(p, `${JSON.stringify(data, null, 2)}\n`, 'utf8')
}

export function applyDashboardTrackerIncrements(
  increments: DashboardTrackerIncrements
): DashboardTrackers {
  const cur = readDashboardTrackers()
  const bump = (
    field: 'scrapesStarted' | 'commentsScraped',
    inc?: number
  ) => {
    if (inc === undefined) {
      return
    }
    const n = clampNonNegative(inc)
    if (n <= 0) {
      return
    }
    cur[field] = clampNonNegative(cur[field] + n)
  }
  bump('scrapesStarted', increments.scrapesStarted)
  bump('commentsScraped', increments.commentsScraped)
  writeDashboardTrackers(cur)
  return cur
}

function sumBytesRecursive(dir: string, depth: number): number {
  if (depth > MAX_TREE_DEPTH) {
    return 0
  }
  let total = 0
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return 0
  }
  for (const e of entries) {
    if (e.name.startsWith('.')) {
      continue
    }
    const p = path.join(dir, e.name)
    try {
      if (e.isDirectory()) {
        total += sumBytesRecursive(p, depth + 1)
      } else if (e.isFile()) {
        total += fs.statSync(p).size
      }
    } catch {
      continue
    }
  }
  return total
}

export function computeTotalStorageBytesUnderAllowedRoots(store: Store): number {
  let sum = 0
  for (const root of getAllowedOutputRoots(store)) {
    const resolved = path.resolve(root)
    if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) {
      continue
    }
    sum += sumBytesRecursive(resolved, 0)
  }
  return sum
}

/** Reads `comments.json` envelope `data.total_count` when present. */
export function readCommentsTotalCountFromOutputDir(outputDir: string): number {
  const p = path.join(outputDir, 'comments.json')
  if (!fs.existsSync(p)) {
    return 0
  }
  try {
    const rawText = fs.readFileSync(p, 'utf8')
    const j = JSON.parse(rawText) as { data?: { total_count?: unknown } }
    const n = j.data?.total_count
    return typeof n === 'number' && Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0
  } catch {
    return 0
  }
}

export function refreshDashboardStorage(store: Store): DashboardTrackers {
  const bytes = computeTotalStorageBytesUnderAllowedRoots(store)
  const cur = readDashboardTrackers()
  cur.totalStorageBytes = bytes
  writeDashboardTrackers(cur)
  return cur
}

/**
 * After a job completes: add lifetime comment count from this folder (if any), then rescan total disk usage.
 */
export function syncDashboardAfterJob(outputDir: string, store: Store): DashboardTrackers {
  if (!outputDir || typeof outputDir !== 'string' || !isOutputDirAllowed(outputDir, store)) {
    return refreshDashboardStorage(store)
  }
  const resolved = path.resolve(outputDir)
  const n = readCommentsTotalCountFromOutputDir(resolved)
  if (n > 0) {
    applyDashboardTrackerIncrements({ commentsScraped: n })
  }
  return refreshDashboardStorage(store)
}

export function flushDashboardTrackers(store: Store): DashboardTrackers {
  const fresh = defaultDashboardTrackers()
  writeDashboardTrackers(fresh)
  return refreshDashboardStorage(store)
}
