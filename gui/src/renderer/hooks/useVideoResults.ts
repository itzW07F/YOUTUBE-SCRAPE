import { useEffect, useMemo, useRef, useState } from 'react'
import type { ScrapeJob } from '../stores/scrapeStore'

export interface MediaFileInfo {
  name: string
  path: string
  type: 'video' | 'audio'
  sizeBytes: number | null
}

export interface VideoResult {
  id: string
  videoId: string
  title: string
  channelTitle: string
  url: string
  outputDir: string
  scrapedAt: string
  hasVideo: boolean
  hasComments: boolean
  hasTranscript: boolean
  hasThumbnails: boolean
  hasDownload: boolean
  thumbnailSources: string[]
  durationSeconds: number | null
  /** ISO timestamp from video.json when present. */
  publishedAt: string | null
  /** Milliseconds since epoch; 0 = unknown. */
  publishedAtMs: number
  viewCount: number | null
  likeCount: number | null
  dislikeCount: number | null
  /** Comment total from ``video.json`` metadata only (not scraped comment file counts). */
  commentCount: number | null
  folderSizeBytes: number | null
}

interface VideoMetaRead {
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
  commentCount: number | null
  folderSizeBytes: number | null
}

function outputLeafName(outputDir?: string): string {
  return outputDir?.split(/[\\/]/).filter(Boolean).pop() || ''
}

function canonicalThumbnailSources(videoId: string): string[] {
  if (!videoId) {
    return []
  }
  return [
    `https://i.ytimg.com/vi_webp/${videoId}/maxresdefault.webp`,
    `https://i.ytimg.com/vi/${videoId}/maxresdefault.jpg`,
    `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`,
  ]
}

function uniqueSources(sources: Array<string | null | undefined>): string[] {
  return Array.from(new Set(sources.filter((source): source is string => Boolean(source))))
}

function createBaseResult(job: ScrapeJob): VideoResult {
  const videoId = outputLeafName(job.outputDir)
  const operations = job.operations ? new Set(job.operations) : null
  return {
    id: job.id,
    videoId,
    title: `Video ${videoId || job.id}`,
    channelTitle: 'Unknown',
    url: job.url,
    outputDir: job.outputDir || '',
    scrapedAt: job.completedAt || job.startedAt || '',
    hasVideo: operations ? operations.has('video') : true,
    hasComments: operations ? operations.has('comments') : job.type === 'all' || job.type === 'comments',
    hasTranscript: operations ? operations.has('transcript') : job.type === 'all' || job.type === 'transcript',
    hasThumbnails: operations ? operations.has('thumbnails') : job.type === 'all' || job.type === 'thumbnails',
    hasDownload: operations ? operations.has('download') : job.type === 'all' || job.type === 'download',
    thumbnailSources: canonicalThumbnailSources(videoId),
    durationSeconds: null,
    publishedAt: null,
    publishedAtMs: 0,
    viewCount: null,
    likeCount: null,
    dislikeCount: null,
    commentCount: null,
    folderSizeBytes: null,
  }
}

/** Same shape as main-process discover; keeps Gallery/Results full after job history is cleared. */
function createBaseResultFromDiscovery(d: {
  outputDir: string
  videoId: string
  url: string
  completedAt: string
}): VideoResult {
  const dir = d.outputDir
  const vidRaw = (d.videoId && d.videoId.length > 0 ? d.videoId : outputLeafName(dir)) || ''
  const short = vidRaw.replace(/[^a-zA-Z0-9_-]/g, '').slice(-12) || 'job'
  const id = `discover-${short}-${dir.slice(-12)}`
  return {
    id,
    videoId: vidRaw,
    title: `Video ${vidRaw || id}`,
    channelTitle: 'Unknown',
    url: d.url,
    outputDir: dir,
    scrapedAt: d.completedAt || '',
    hasVideo: true,
    hasComments: true,
    hasTranscript: true,
    hasThumbnails: true,
    hasDownload: true,
    thumbnailSources: canonicalThumbnailSources(vidRaw),
    durationSeconds: null,
    publishedAt: null,
    publishedAtMs: 0,
    viewCount: null,
    likeCount: null,
    dislikeCount: null,
    commentCount: null,
    folderSizeBytes: null,
  }
}

function outputDirKey(dir: string): string {
  return dir.replace(/[\\/]+$/, '')
}

function fingerprintVideoResults(list: VideoResult[]): string {
  return list
    .map(
      (r) =>
        [
          r.id,
          r.outputDir,
          r.videoId,
          r.title,
          r.channelTitle,
          String(r.durationSeconds ?? ''),
          r.publishedAt ?? '',
          String(r.publishedAtMs),
          String(r.viewCount ?? ''),
          String(r.likeCount ?? ''),
          String(r.dislikeCount ?? ''),
          String(r.commentCount ?? ''),
          String(r.folderSizeBytes ?? ''),
          r.thumbnailSources.join('\x1c'),
        ].join('\x1d')
    )
    .join('\x1e')
}

export function useVideoResults(jobs: ScrapeJob[], diskRevision = 0): VideoResult[] {
  const fromCompletedJobs = useMemo(
    () =>
      jobs
        .filter((job) => job.status === 'completed' && job.outputDir)
        .map(createBaseResult),
    [jobs]
  )
  const [results, setResults] = useState<VideoResult[]>([])
  const lastFingerprintRef = useRef<string>('')

  useEffect(() => {
    let cancelled = false

    void (async () => {
      const byDir = new Map<string, VideoResult>()
      for (const r of fromCompletedJobs) {
        byDir.set(outputDirKey(r.outputDir), r)
      }

      if (window.electronAPI?.discoverScrapeOutputs) {
        try {
          const discovered = (await window.electronAPI.discoverScrapeOutputs()) as Array<{
            outputDir: string
            videoId: string
            url: string
            completedAt: string
          }>
          for (const row of discovered) {
            const key = outputDirKey(row.outputDir)
            if (!key || byDir.has(key)) {
              continue
            }
            byDir.set(key, createBaseResultFromDiscovery(row))
          }
        } catch {
          // Non-fatal: fall back to job-derived rows only
        }
      }

      const baseList = Array.from(byDir.values())
      if (!baseList.length) {
        if (!cancelled) {
          lastFingerprintRef.current = ''
          setResults([])
        }
        return
      }

      if (!window.electronAPI) {
        if (!cancelled) {
          const deduped = dedupeVideoResults(baseList)
          const fp = `${diskRevision}\x1f${fingerprintVideoResults(deduped)}`
          if (fp !== lastFingerprintRef.current) {
            lastFingerprintRef.current = fp
            setResults(deduped)
          }
        }
        return
      }

      const next: VideoResult[] = []

      for (const result of baseList) {
        if (cancelled) {
          return
        }

        let videoId = result.videoId
        let title = result.title
        let channelTitle = result.channelTitle
        const thumbnailSources: Array<string | null | undefined> = []
        let meta: VideoMetaRead | null = null

        try {
          meta = (await window.electronAPI.readOutputVideoMeta(result.outputDir)) as VideoMetaRead | null
          if (meta) {
            if (!meta.hasArtifacts) {
              continue
            }
            videoId = meta.videoId || videoId
            title = meta.title || title
            channelTitle = meta.channelTitle || channelTitle
            thumbnailSources.push(
              meta.localThumbPath ? window.electronAPI.getAppMediaUrl(meta.localThumbPath) : '',
              meta.thumbnailUrl || '',
              ...canonicalThumbnailSources(videoId)
            )
          }
        } catch {
          meta = null
          // Keep row metadata and canonical thumbnail fallbacks
        }

        thumbnailSources.push(...result.thumbnailSources)

        next.push({
          ...result,
          videoId,
          title,
          channelTitle,
          thumbnailSources: uniqueSources(thumbnailSources),
          durationSeconds: meta?.durationSeconds ?? result.durationSeconds,
          publishedAt: meta?.publishedAt ?? result.publishedAt,
          publishedAtMs:
            meta?.publishedAt && Number.isFinite(Date.parse(meta.publishedAt))
              ? Date.parse(meta.publishedAt)
              : result.publishedAtMs,
          viewCount: meta?.viewCount ?? result.viewCount,
          likeCount: meta?.likeCount ?? result.likeCount,
          dislikeCount: meta?.dislikeCount ?? result.dislikeCount,
          commentCount: meta?.commentCount ?? result.commentCount,
          folderSizeBytes: meta?.folderSizeBytes ?? result.folderSizeBytes,
        })
      }

      if (!cancelled) {
        const deduped = dedupeVideoResults(next)
        // Include diskRevision so gallery re-syncs after metadata refresh even when visible fields match
        // previous reads (fingerprints omit some fields).
        const fp = `${diskRevision}\x1f${fingerprintVideoResults(deduped)}`
        if (fp === lastFingerprintRef.current) {
          return
        }
        lastFingerprintRef.current = fp
        setResults(deduped)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [fromCompletedJobs, diskRevision])

  return results
}

function resultTime(result: VideoResult): number {
  const parsed = Date.parse(result.scrapedAt)
  return Number.isFinite(parsed) ? parsed : 0
}

function dedupeVideoResults(results: VideoResult[]): VideoResult[] {
  const byVideo = new Map<string, VideoResult>()

  for (const result of results) {
    const key = result.videoId || result.outputDir || result.id
    const existing = byVideo.get(key)
    if (!existing) {
      byVideo.set(key, result)
      continue
    }

    const shouldReplace =
      result.hasDownload !== existing.hasDownload
        ? result.hasDownload
        : resultTime(result) >= resultTime(existing)
    if (shouldReplace) {
      byVideo.set(key, result)
    }
  }

  return Array.from(byVideo.values()).sort((a, b) => resultTime(b) - resultTime(a))
}
