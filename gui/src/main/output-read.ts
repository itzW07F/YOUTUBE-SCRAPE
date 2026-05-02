import fs from 'node:fs'
import path from 'node:path'
import type Store from 'electron-store'
import { readCommentsTotalCountFromOutputDir } from './dashboard-trackers-file'
import {
  getAllowedOutputRoots,
  isOutputDirAllowed,
  isPathAllowedForMedia,
} from './media-serve'

export interface VideoMetaRead {
  hasArtifacts: boolean
  videoId: string | null
  title: string | null
  channelTitle: string | null
  thumbnailUrl: string | null
  localThumbPath: string | null
  durationSeconds: number | null
  publishedAt: string | null
  viewCount: number | null
  likeCount: number | null
  dislikeCount: number | null
  /** From ``video.json`` metadata (watch layout / initial data). Not inferred from ``comments.json``. */
  commentCount: number | null
  folderSizeBytes: number | null
  /**
   * When true, this output folder may be listed in Results / Video Gallery.
   * Skips runs that only produced markers like summary.json or an empty shell video.json.
   */
  eligibleForBrowseUi: boolean
}

export interface MediaFileInfo {
  name: string
  path: string
  type: 'video' | 'audio'
  /** File size on disk; null if stat failed. */
  sizeBytes: number | null
}

export type OutputArtifactKind = 'video' | 'comments' | 'transcript' | 'thumbnails' | 'media' | 'summary'

export interface OutputArtifactRead {
  kind: OutputArtifactKind
  fileName: string | null
  contentType: 'json' | 'text' | 'images' | 'media'
  content: string | null
  truncated: boolean
  images: Array<{ name: string; path: string }>
  media: MediaFileInfo[]
}

const MAX_ARTIFACT_BYTES = 5 * 1024 * 1024

function readTextArtifact(filePath: string): { content: string; truncated: boolean } {
  const stat = fs.statSync(filePath)
  if (stat.size <= MAX_ARTIFACT_BYTES) {
    return { content: fs.readFileSync(filePath, 'utf8'), truncated: false }
  }
  const fd = fs.openSync(filePath, 'r')
  try {
    const buffer = Buffer.alloc(MAX_ARTIFACT_BYTES)
    fs.readSync(fd, buffer, 0, MAX_ARTIFACT_BYTES, 0)
    return { content: buffer.toString('utf8'), truncated: true }
  } finally {
    fs.closeSync(fd)
  }
}

function firstExistingFile(outputDir: string, names: string[]): string | null {
  for (const name of names) {
    const candidate = path.join(outputDir, name)
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      return candidate
    }
  }
  return null
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

/** Prefer ``data`` payload when present (ResultEnvelope); else whole root (legacy flat dump). */
function envelopeDataRoot(envelope: Record<string, unknown>): Record<string, unknown> {
  const inner = envelope.data
  if (inner !== null && typeof inner === 'object' && !Array.isArray(inner)) {
    return inner as Record<string, unknown>
  }
  return envelope
}

function metadataRecordFromVideoJson(envelope: Record<string, unknown>): Record<string, unknown> | null {
  const root = envelopeDataRoot(envelope)
  return asRecord(root.metadata)
}

function pickMetaUnknown(meta: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(meta, key)) {
      const value = meta[key]
      if (value !== undefined && value !== null) {
        return value
      }
    }
  }
  return undefined
}

function pickMetaString(meta: Record<string, unknown>, keys: string[]): string | null {
  const v = pickMetaUnknown(meta, keys)
  if (typeof v === 'string' && v.trim() !== '') {
    return v.trim()
  }
  return null
}

/** Accepts ISO strings or epoch seconds/ms (some tooling exports numbers). */
function parsePublishedAtField(value: unknown): string | null {
  if (typeof value === 'string' && value.trim() !== '') {
    return value.trim()
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const ms = value > 1e12 ? value : value * 1000
    const d = new Date(ms)
    if (Number.isFinite(d.getTime())) {
      return d.toISOString()
    }
  }
  return null
}

function optFiniteInt(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.trunc(value)
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const normalized = value.trim().replace(/[,_\s\u202f]/g, '')
    const n = Number(normalized)
    if (Number.isFinite(n)) {
      return Math.trunc(n)
    }
  }
  return null
}

/** Total size of files under ``outputDir`` (stays within resolved output tree). */
function sumOutputDirectoryBytes(outputDir: string, store: Store): number | null {
  if (!isOutputDirAllowed(outputDir, store)) {
    return null
  }
  const resolvedRoot = path.resolve(outputDir)
  let total = 0
  const walk = (dir: string): void => {
    let entries: string[]
    try {
      entries = fs.readdirSync(dir)
    } catch {
      return
    }
    for (const name of entries) {
      const full = path.join(dir, name)
      const resolved = path.resolve(full)
      if (resolved !== resolvedRoot && !resolved.startsWith(resolvedRoot + path.sep)) {
        continue
      }
      let st: fs.Stats
      try {
        st = fs.statSync(full)
      } catch {
        continue
      }
      if (st.isDirectory()) {
        walk(full)
      } else if (st.isFile()) {
        total += st.size
      }
    }
  }
  try {
    walk(resolvedRoot)
  } catch {
    return null
  }
  return total
}

export function readOutputArtifact(
  outputDir: string,
  kind: OutputArtifactKind,
  store: Store
): OutputArtifactRead | null {
  if (!isOutputDirAllowed(outputDir, store)) {
    return null
  }

  if (kind === 'media') {
    return {
      kind,
      fileName: null,
      contentType: 'media',
      content: null,
      truncated: false,
      images: [],
      media: listOutputDownloadMedia(outputDir, store)
    }
  }

  if (kind === 'thumbnails') {
    const thumbnailsDir = path.join(outputDir, 'thumbnails')
    const images =
      fs.existsSync(thumbnailsDir) && fs.statSync(thumbnailsDir).isDirectory()
        ? fs
            .readdirSync(thumbnailsDir)
            .filter((name) => /\.(jpe?g|png|webp|gif)$/i.test(name))
            .map((name) => ({ name, path: path.join(thumbnailsDir, name) }))
            .filter((image) => isPathAllowedForMedia(image.path, store))
        : []
    const metadataPath = firstExistingFile(outputDir, ['thumbnails.json'])
    const metadata = metadataPath ? readTextArtifact(metadataPath) : { content: null, truncated: false }
    return {
      kind,
      fileName: metadataPath ? path.basename(metadataPath) : null,
      contentType: 'images',
      content: metadata.content,
      truncated: metadata.truncated,
      images,
      media: []
    }
  }

  const artifactPath =
    kind === 'video'
      ? firstExistingFile(outputDir, ['video.json'])
      : kind === 'comments'
        ? firstExistingFile(outputDir, ['comments.json'])
        : kind === 'transcript'
          ? firstExistingFile(outputDir, ['transcript.txt', 'transcript.vtt', 'transcript.json'])
          : firstExistingFile(outputDir, ['summary.json'])

  if (!artifactPath) {
    return null
  }

  const read = readTextArtifact(artifactPath)
  return {
    kind,
    fileName: path.basename(artifactPath),
    contentType: path.extname(artifactPath).toLowerCase() === '.json' ? 'json' : 'text',
    content: read.content,
    truncated: read.truncated,
    images: [],
    media: []
  }
}

function outputDirHasTranscriptBody(absOutputDir: string): boolean {
  for (const tf of ['transcript.txt', 'transcript.vtt', 'transcript.json']) {
    const tp = path.join(absOutputDir, tf)
    try {
      if (fs.existsSync(tp) && fs.statSync(tp).isFile() && fs.statSync(tp).size > 48) {
        return true
      }
    } catch {
      /* ignore */
    }
  }
  return false
}

function videoMetaIsUsableForBrowse(meta: VideoMetaRead): boolean {
  return (
    Boolean(meta.title?.trim()) ||
    Boolean(meta.channelTitle?.trim()) ||
    meta.viewCount != null ||
    meta.durationSeconds != null ||
    meta.likeCount != null ||
    meta.dislikeCount != null ||
    Boolean(meta.publishedAt?.trim()) ||
    (meta.commentCount != null && meta.commentCount > 0)
  )
}

/**
 * Results / Video Gallery list only folders the user can actually browse (media, comments, transcript,
 * thumbnails on disk, or non-trivial video metadata). Failed / gated scrapes that only left summary.json
 * or an empty envelope stay on Scrape Jobs only.
 */
function outputDirEligibleForBrowseUi(resolvedDir: string, store: Store, meta: VideoMetaRead): boolean {
  const abs = path.resolve(resolvedDir)
  if (!isOutputDirAllowed(abs, store)) {
    return false
  }

  const summaryPath = path.join(abs, 'summary.json')
  if (fs.existsSync(summaryPath)) {
    try {
      const s = JSON.parse(fs.readFileSync(summaryPath, 'utf8')) as Record<string, unknown>
      if (s.fatal_access_abort === true) {
        return false
      }
      if (s.job_status === 'failed') {
        return false
      }
    } catch {
      /* ignore malformed summary */
    }
  }

  if (listOutputDownloadMedia(abs, store).length > 0) {
    return true
  }

  const thumbDir = path.join(abs, 'thumbnails')
  if (fs.existsSync(thumbDir) && fs.statSync(thumbDir).isDirectory()) {
    try {
      if (fs.readdirSync(thumbDir).some((f) => /\.(jpe?g|png|webp|gif)$/i.test(f))) {
        return true
      }
    } catch {
      /* ignore */
    }
  }

  if (outputDirHasTranscriptBody(abs)) {
    return true
  }

  if (readCommentsTotalCountFromOutputDir(abs) > 0) {
    return true
  }
  try {
    const cp = path.join(abs, 'comments.json')
    if (fs.existsSync(cp)) {
      const j = JSON.parse(fs.readFileSync(cp, 'utf8')) as { data?: { comments?: unknown[] } }
      if (Array.isArray(j.data?.comments) && j.data.comments.length > 0) {
        return true
      }
    }
  } catch {
    /* ignore */
  }

  return videoMetaIsUsableForBrowse(meta)
}

export function readOutputVideoMeta(outputDir: string, store: Store): VideoMetaRead | null {
  if (!isOutputDirAllowed(outputDir, store)) {
    return null
  }
  const out: VideoMetaRead = {
    hasArtifacts: false,
    videoId: null,
    title: null,
    channelTitle: null,
    thumbnailUrl: null,
    localThumbPath: null,
    durationSeconds: null,
    publishedAt: null,
    viewCount: null,
    likeCount: null,
    dislikeCount: null,
    commentCount: null,
    folderSizeBytes: null,
    eligibleForBrowseUi: false,
  }
  const videoJson = path.join(outputDir, 'video.json')
  if (fs.existsSync(videoJson)) {
    out.hasArtifacts = true
    try {
      const raw = fs.readFileSync(videoJson, 'utf8')
      const parsed = JSON.parse(raw) as unknown
      const j = asRecord(parsed)
      const m = j ? metadataRecordFromVideoJson(j) : null
      if (m) {
        const videoId = pickMetaString(m, ['video_id', 'videoId'])
        if (videoId) {
          out.videoId = videoId
        }
        const title = pickMetaString(m, ['title'])
        if (title) {
          out.title = title
        }
        const channelTitle = pickMetaString(m, ['channel_title', 'channelTitle'])
        if (channelTitle) {
          out.channelTitle = channelTitle
        }
        out.durationSeconds = optFiniteInt(
          pickMetaUnknown(m, ['duration_seconds', 'durationSeconds', 'length_seconds'])
        )
        const publishedRaw = pickMetaUnknown(m, ['published_at', 'publishedAt'])
        const published = parsePublishedAtField(publishedRaw)
        if (published) {
          out.publishedAt = published
        }
        out.viewCount = optFiniteInt(pickMetaUnknown(m, ['view_count', 'viewCount', 'views']))
        out.likeCount = optFiniteInt(pickMetaUnknown(m, ['like_count', 'likeCount', 'likes']))
        out.dislikeCount = optFiniteInt(pickMetaUnknown(m, ['dislike_count', 'dislikeCount', 'dislikes']))
        out.commentCount = optFiniteInt(pickMetaUnknown(m, ['comment_count', 'commentCount']))
        const thumbsRaw = m.thumbnails
        const thumbs = Array.isArray(thumbsRaw) ? thumbsRaw : []
        let best: { url: string; width?: number; height?: number } | undefined
        for (const entry of thumbs) {
          const t = asRecord(entry)
          if (!t || typeof t.url !== 'string' || !t.url) {
            continue
          }
          const cand = { url: t.url, width: optFiniteInt(t.width) ?? undefined, height: optFiniteInt(t.height) ?? undefined }
          if (best == null) {
            best = cand
            continue
          }
          const aw = (cand.width ?? 0) * (cand.height ?? 0)
          const bw = (best.width ?? 0) * (best.height ?? 0)
          if (aw > bw) {
            best = cand
          }
        }
        if (best?.url) {
          out.thumbnailUrl = best.url
        }
      }
    } catch {
      // ignore
    }
  }
  const td = path.join(outputDir, 'thumbnails')
  if (fs.existsSync(td) && fs.statSync(td).isDirectory()) {
    const files = fs.readdirSync(td).filter((f) => /\.(jpe?g|png|webp|gif)$/i.test(f))
    if (files.length) {
      const first =
        files.find((f) => /maxres|hqdefault|maxresdefault|1280x720|1280_720|sddefault|960|640/i.test(f)) ||
        files.sort().pop() ||
        files[0]
      const p = path.join(td, first)
      if (isPathAllowedForMedia(p, store)) {
        out.hasArtifacts = true
        out.localThumbPath = p
      }
    }
  }
  for (const name of ['comments.json', 'transcript.txt', 'transcript.vtt', 'transcript.json', 'thumbnails.json', 'summary.json']) {
    const artifactPath = path.join(outputDir, name)
    if (fs.existsSync(artifactPath) && fs.statSync(artifactPath).isFile()) {
      out.hasArtifacts = true
      break
    }
  }
  if (!out.hasArtifacts && listOutputDownloadMedia(outputDir, store).length > 0) {
    out.hasArtifacts = true
  }
  try {
    out.folderSizeBytes = sumOutputDirectoryBytes(outputDir, store)
  } catch {
    out.folderSizeBytes = null
  }
  out.eligibleForBrowseUi = outputDirEligibleForBrowseUi(outputDir, store, out)
  return out
}

export function listOutputDownloadMedia(outputDir: string, store: Store): MediaFileInfo[] {
  if (!isOutputDirAllowed(outputDir, store)) {
    return []
  }
  const downloadDir = path.join(outputDir, 'download')
  if (!fs.existsSync(downloadDir) || !fs.statSync(downloadDir).isDirectory()) {
    return []
  }
  const list: MediaFileInfo[] = []
  for (const name of fs.readdirSync(downloadDir)) {
    const full = path.join(downloadDir, name)
    if (!fs.statSync(full).isFile()) {
      continue
    }
    if (!isPathAllowedForMedia(full, store)) {
      continue
    }
    const ext = path.extname(name).toLowerCase()
    let sizeBytes: number | null = null
    try {
      sizeBytes = fs.statSync(full).size
    } catch {
      sizeBytes = null
    }
    if (['.mp4', '.webm', '.mkv', '.m4v', '.mov'].includes(ext)) {
      list.push({ name, path: full, type: 'video', sizeBytes })
    } else if (['.m4a', '.mp3', '.opus', '.ogg', '.wav', '.aac', '.flac'].includes(ext)) {
      list.push({ name, path: full, type: 'audio', sizeBytes })
    }
  }
  return list
}

export function toAppMediaUrl(absoluteFilePath: string): string {
  const p = Buffer.from(absoluteFilePath, 'utf8').toString('base64url')
  return `appmedia://local/?p=${encodeURIComponent(p)}`
}

const MAX_OUTPUT_SCAN_DEPTH = 10

interface DiscoveredScrapeRow {
  outputDir: string
  videoId: string
  url: string
  completedAt: string
}

function pushDiscoveredIfVideoJson(dirAbs: string, seen: Set<string>, results: DiscoveredScrapeRow[]): void {
  const abs = path.resolve(dirAbs)
  const vj = path.join(abs, 'video.json')
  if (!fs.existsSync(vj) || !fs.statSync(vj).isFile()) {
    return
  }
  if (seen.has(abs)) {
    return
  }
  seen.add(abs)
  const st = fs.statSync(abs)
  const mtime = new Date(st.mtimeMs).toISOString()
  const name = path.basename(abs)
  let videoId = name
  let url = `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`
  try {
    const raw = fs.readFileSync(vj, 'utf8')
    const j = JSON.parse(raw) as { data?: { metadata?: { video_id?: string } } }
    const id = j.data?.metadata?.video_id
    if (id) {
      videoId = id
      url = `https://www.youtube.com/watch?v=${id}`
    }
  } catch {
    // use folder name
  }
  results.push({
    outputDir: abs,
    videoId,
    url,
    completedAt: mtime
  })
}

/** Depth-first: supports output/<id>, output/reference/<id>, legacy api/output/<id>, etc. */
function scanForVideoJsonDirs(absoluteRoot: string, depth: number, seen: Set<string>, out: DiscoveredScrapeRow[]): void {
  if (depth > MAX_OUTPUT_SCAN_DEPTH) {
    return
  }
  if (!fs.existsSync(absoluteRoot) || !fs.statSync(absoluteRoot).isDirectory()) {
    return
  }
  const resolvedRoot = path.resolve(absoluteRoot)
  let entries: string[]
  try {
    entries = fs.readdirSync(resolvedRoot)
  } catch {
    return
  }
  for (const name of entries) {
    if (name.startsWith('.')) {
      continue
    }
    const sub = path.join(resolvedRoot, name)
    let isDir: boolean
    try {
      isDir = fs.statSync(sub).isDirectory()
    } catch {
      continue
    }
    if (!isDir) {
      continue
    }
    pushDiscoveredIfVideoJson(sub, seen, out)
    const hasVideo = fs.existsSync(path.join(sub, 'video.json'))
    if (hasVideo) {
      continue
    }
    scanForVideoJsonDirs(sub, depth + 1, seen, out)
  }
}

/**
 * Remove a single scrape output folder (must be a subdirectory of an allowed root, not the root itself).
 */
export function deleteOutputScrapeDir(
  outputDir: string,
  store: Store
): { ok: boolean; error?: string } {
  if (!outputDir || typeof outputDir !== 'string') {
    return { ok: false, error: 'Invalid path' }
  }
  const resolved = path.resolve(outputDir)
  if (!isOutputDirAllowed(resolved, store)) {
    return { ok: false, error: 'Folder is outside the configured output directory' }
  }
  const roots = getAllowedOutputRoots(store)
  for (const root of roots) {
    if (resolved === path.resolve(root)) {
      return { ok: false, error: 'Cannot delete an output root directory' }
    }
  }
  try {
    if (!fs.existsSync(resolved)) {
      return { ok: true }
    }
    if (!fs.statSync(resolved).isDirectory()) {
      return { ok: false, error: 'Path is not a directory' }
    }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
  try {
    fs.rmSync(resolved, { recursive: true, force: true })
    return { ok: true }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

/** Scan allowed output root dirs for video.json folders (for rehydration after restart). */
export function discoverScrapeOutputs(store: Store): Array<{
  outputDir: string
  videoId: string
  url: string
  completedAt: string
}> {
  const results: Array<{
    outputDir: string
    videoId: string
    url: string
    completedAt: string
  }> = []
  const seen = new Set<string>()
  for (const root of getAllowedOutputRoots(store)) {
    if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
      continue
    }
    scanForVideoJsonDirs(path.resolve(root), 0, seen, results)
  }
  return results.filter((r) => {
    const meta = readOutputVideoMeta(r.outputDir, store)
    return meta !== null && meta.eligibleForBrowseUi
  })
}
