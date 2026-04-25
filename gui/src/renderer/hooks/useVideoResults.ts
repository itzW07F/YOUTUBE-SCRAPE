import { useEffect, useMemo, useState } from 'react'
import type { ScrapeJob } from '../stores/scrapeStore'

export interface MediaFileInfo {
  name: string
  path: string
  type: 'video' | 'audio'
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
}

interface VideoMetaRead {
  hasArtifacts: boolean
  videoId: string | null
  title: string | null
  channelTitle: string | null
  thumbnailUrl: string | null
  localThumbPath: string | null
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
  }
}

export function useVideoResults(jobs: ScrapeJob[]): VideoResult[] {
  const baseResults = useMemo(
    () => jobs.filter((job) => job.status === 'completed' && job.outputDir).map(createBaseResult),
    [jobs]
  )
  const [results, setResults] = useState<VideoResult[]>([])

  useEffect(() => {
    if (!baseResults.length) {
      setResults([])
      return
    }

    if (!window.electronAPI) {
      setResults(baseResults)
      return
    }

    let cancelled = false

    void (async () => {
      const next: VideoResult[] = []

      for (const result of baseResults) {
        if (cancelled) {
          return
        }

        let videoId = result.videoId
        let title = result.title
        let channelTitle = result.channelTitle
        const thumbnailSources: Array<string | null | undefined> = []

        try {
          const meta = (await window.electronAPI.readOutputVideoMeta(result.outputDir)) as VideoMetaRead | null
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
          // Keep the persisted job metadata and canonical thumbnail fallbacks.
        }

        thumbnailSources.push(...result.thumbnailSources)

        next.push({
          ...result,
          videoId,
          title,
          channelTitle,
          thumbnailSources: uniqueSources(thumbnailSources),
        })
      }

      if (!cancelled) {
        setResults(dedupeVideoResults(next))
      }
    })()

    return () => {
      cancelled = true
    }
  }, [baseResults])

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
