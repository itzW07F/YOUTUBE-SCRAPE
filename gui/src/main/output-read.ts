import fs from 'node:fs'
import path from 'node:path'
import type Store from 'electron-store'
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
}

export interface MediaFileInfo {
  name: string
  path: string
  type: 'video' | 'audio'
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
    localThumbPath: null
  }
  const videoJson = path.join(outputDir, 'video.json')
  if (fs.existsSync(videoJson)) {
    out.hasArtifacts = true
    try {
      const raw = fs.readFileSync(videoJson, 'utf8')
      const j = JSON.parse(raw) as {
        data?: {
          metadata?: {
            video_id?: string
            title?: string
            channel_title?: string
            thumbnails?: { url: string; width?: number; height?: number }[]
          }
        }
      }
      const m = j.data?.metadata
      if (m?.video_id) {
        out.videoId = m.video_id
      }
      if (m?.title) {
        out.title = m.title
      }
      if (m?.channel_title) {
        out.channelTitle = m.channel_title
      }
      const thumbs = m?.thumbnails ?? []
      let best = thumbs[0]
      for (const t of thumbs) {
        if (best == null) {
          best = t
          continue
        }
        if ((t.width ?? 0) * (t.height ?? 0) > (best.width ?? 0) * (best.height ?? 0)) {
          best = t
        }
      }
      if (best?.url) {
        out.thumbnailUrl = best.url
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
    if (['.mp4', '.webm', '.mkv', '.m4v', '.mov'].includes(ext)) {
      list.push({ name, path: full, type: 'video' })
    } else if (['.m4a', '.mp3', '.opus', '.ogg', '.wav', '.aac', '.flac'].includes(ext)) {
      list.push({ name, path: full, type: 'audio' })
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
  return results
}
