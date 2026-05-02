/** Resolve human-readable titles when scrape output has no usable ``video.json`` title. */

const YT_VIDEO_ID_IN_URL = /(?:youtube\.com\/(?:watch\?(?:[^#&]*&)*v=|embed\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/

export function extractYoutubeVideoId(urlOrId: string | undefined | null): string | null {
  if (!urlOrId) {
    return null
  }
  const raw = urlOrId.trim()
  if (/^[a-zA-Z0-9_-]{11}$/.test(raw)) {
    return raw
  }
  const m = raw.match(YT_VIDEO_ID_IN_URL)
  return m?.[1] ?? null
}

export function outputFolderBasenameAsVideoId(outputDir: string | undefined | null): string | null {
  if (!outputDir) {
    return null
  }
  const leaf = outputDir.replace(/[\\/]+$/, '').split(/[\\/]/).filter(Boolean).pop() ?? ''
  return /^[a-zA-Z0-9_-]{11}$/.test(leaf) ? leaf : null
}

export interface YoutubeOEmbedInfo {
  title: string
  authorName: string | null
}

type OembedCacheEntry = Promise<YoutubeOEmbedInfo | null>

const oembedCache = new Map<string, OembedCacheEntry>()

async function fetchYoutubeOembedUncached(videoId: string): Promise<YoutubeOEmbedInfo | null> {
  const watch = `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`
  const endpoint = `https://www.youtube.com/oembed?url=${encodeURIComponent(watch)}&format=json`
  try {
    const res = await fetch(endpoint, { signal: AbortSignal.timeout(10_000) })
    if (!res.ok) {
      return null
    }
    const j = (await res.json()) as { title?: unknown; author_name?: unknown }
    const title = typeof j.title === 'string' ? j.title.trim() : ''
    if (!title) {
      return null
    }
    const authorName =
      typeof j.author_name === 'string' && j.author_name.trim() ? j.author_name.trim() : null
    return { title, authorName }
  } catch {
    return null
  }
}

/** Cached; safe for concurrent callers (e.g. Jobs list + Results scanning the same id). */
export function fetchYoutubeOembedDisplay(videoId: string): OembedCacheEntry {
  let pending = oembedCache.get(videoId)
  if (pending) {
    return pending
  }
  pending = fetchYoutubeOembedUncached(videoId)
  oembedCache.set(videoId, pending)
  void pending.finally(() => {
    window.setTimeout(() => oembedCache.delete(videoId), 120_000)
  })
  return pending
}

export function fallbackYoutubeListTitle(videoId: string | null | undefined): string {
  const id = videoId?.trim()
  return id ? `Video ${id}` : 'Video (unknown id)'
}
