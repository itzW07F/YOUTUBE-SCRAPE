import fs from 'node:fs'
import path from 'node:path'
import { Readable } from 'node:stream'
import type { Session } from 'electron'
import { session } from 'electron'
import type Store from 'electron-store'

const MEDIA_EXTS = new Set([
  '.mp4', '.webm', '.mkv', '.m4v', '.mov',
  '.m4a', '.mp3', '.opus', '.ogg', '.wav', '.aac', '.flac',
  '.jpg', '.jpeg', '.png', '.webp', '.gif', '.json'
])

const EXT_TO_MIME: Record<string, string> = {
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mkv': 'video/x-matroska',
  '.m4v': 'video/x-m4v',
  '.mov': 'video/quicktime',
  '.m4a': 'audio/mp4',
  '.mp3': 'audio/mpeg',
  '.opus': 'audio/ogg',
  '.ogg': 'audio/ogg',
  '.wav': 'audio/wav',
  '.aac': 'audio/aac',
  '.flac': 'audio/flac',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.json': 'application/json'
}

function contentTypeForPath(absolute: string): string {
  const ext = path.extname(absolute).toLowerCase()
  return EXT_TO_MIME[ext] ?? 'application/octet-stream'
}

/**
 * HTTP Range: single `bytes=`-range so HTML5 &lt;video&gt; can seek and buffer.
 * See https://github.com/electron/electron/issues/38749
 */
function appMediaResponse(absolute: string, request: Request): Response {
  const abs = path.resolve(absolute)
  let stat: fs.Stats
  try {
    stat = fs.statSync(abs)
  } catch {
    return new Response('Not found', { status: 404 })
  }
  const size = stat.size
  if (!stat.isFile() || size === 0) {
    return new Response('Empty or not a file', { status: 400 })
  }
  const contentType = contentTypeForPath(abs)
  const rangeHeader = request.headers.get('range')
  if (!rangeHeader || !rangeHeader.startsWith('bytes=')) {
    const body = Readable.toWeb(fs.createReadStream(abs)) as import('node:stream/web').ReadableStream
    return new Response(body, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(size),
        'Accept-Ranges': 'bytes'
      }
    })
  }
  const m = /^bytes=(\d*)-(\d*)$/.exec(rangeHeader)
  if (!m) {
    const body = Readable.toWeb(fs.createReadStream(abs)) as import('node:stream/web').ReadableStream
    return new Response(body, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(size),
        'Accept-Ranges': 'bytes'
      }
    })
  }
  const startStr = m[1]
  const endStr = m[2]
  let start: number
  let end: number
  if (startStr === '' && endStr !== '') {
    const suffix = Number.parseInt(endStr, 10)
    if (!Number.isFinite(suffix) || suffix <= 0) {
      return new Response('Invalid range', { status: 400 })
    }
    start = Math.max(0, size - suffix)
    end = size - 1
  } else {
    start = startStr !== '' ? Number.parseInt(startStr, 10) : 0
    end = endStr !== '' ? Number.parseInt(endStr, 10) : size - 1
  }
  if (Number.isNaN(start) || Number.isNaN(end) || start < 0 || start >= size) {
    return new Response(null, {
      status: 416,
      headers: { 'Content-Range': `bytes */${size}` }
    })
  }
  end = Math.min(end, size - 1)
  if (end < start) {
    return new Response(null, {
      status: 416,
      headers: { 'Content-Range': `bytes */${size}` }
    })
  }
  const chunk = end - start + 1
  const body = Readable.toWeb(
    fs.createReadStream(abs, { start, end })
  ) as import('node:stream/web').ReadableStream
  return new Response(body, {
    status: 206,
    headers: {
      'Content-Type': contentType,
      'Content-Range': `bytes ${start}-${end}/${size}`,
      'Content-Length': String(chunk),
      'Accept-Ranges': 'bytes'
    }
  })
}

export function getRepoOutputDirFromMain(__dirname: string): string {
  return path.resolve(path.join(__dirname, '..', '..', '..', 'output'))
}

/**
 * When the server was started with CWD = api/, scrapes were written to src/youtube_scrape/api/output/.
 * Keep this path allowed and discoverable so existing runs still show in the UI.
 */
export function getLegacyPythonApiOutputDirFromMain(__dirname: string): string {
  const repoRoot = path.resolve(path.join(__dirname, '..', '..', '..'))
  return path.join(repoRoot, 'src', 'youtube_scrape', 'api', 'output')
}

export function getAllowedOutputRoots(store: Store): string[] {
  const mainDir = typeof __filename !== 'undefined' ? path.dirname(__filename) : 'gui/out/main'
  const roots: string[] = [getRepoOutputDirFromMain(mainDir)]
  const legacy = getLegacyPythonApiOutputDirFromMain(mainDir)
  if (fs.existsSync(legacy) && fs.statSync(legacy).isDirectory()) {
    roots.push(path.resolve(legacy))
  }
  const custom = store.get('outputDirectory') as string | undefined
  if (custom && typeof custom === 'string' && custom.length > 0) {
    const resolved = path.resolve(custom)
    if (!roots.some((r) => path.resolve(r) === resolved)) {
      roots.push(resolved)
    }
  }
  return roots
}

function allowedRoots(store: Store): string[] {
  return getAllowedOutputRoots(store)
}

function isUnderAnyRoot(absolute: string, store: Store): boolean {
  const r = path.resolve(absolute)
  for (const root of allowedRoots(store)) {
    const norm = path.resolve(root)
    if (r === norm || r.startsWith(norm + path.sep)) {
      return true
    }
  }
  return false
}

export function isPathAllowedForMedia(absolute: string, store: Store): boolean {
  if (!isUnderAnyRoot(absolute, store)) {
    return false
  }
  if (!MEDIA_EXTS.has(path.extname(absolute).toLowerCase())) {
    return false
  }
  try {
    if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
      return false
    }
  } catch {
    return false
  }
  return true
}

export function isOutputDirAllowed(dir: string, store: Store): boolean {
  return isUnderAnyRoot(path.resolve(dir), store)
}

export function registerAppMediaProtocol(s: Session, store: Store): void {
  s.protocol.handle('appmedia', async (request) => {
    try {
      const u = new URL(request.url)
      const p = u.searchParams.get('p')
      if (!p) {
        return new Response('Missing path', { status: 400 })
      }
      const abs = Buffer.from(p, 'base64url').toString('utf8')
      if (!isPathAllowedForMedia(abs, store)) {
        return new Response('Forbidden', { status: 403 })
      }
      return appMediaResponse(abs, request)
    } catch (e) {
      return new Response(e instanceof Error ? e.message : String(e), { status: 500 })
    }
  })
}

/**
 * Public entry: register the appmedia: protocol (call once before loading windows).
 */
export function setupAppMediaProtocol(store: Store): void {
  registerAppMediaProtocol(session.defaultSession, store)
}
