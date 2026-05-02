import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownWideNarrow, ArrowUpNarrowWide, FolderOpen, Image, RefreshCw, Search, Trash2, Video } from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'
import { MediaFileInfo, useVideoResults, VideoResult } from '../hooks/useVideoResults'
import { useGalleryPlayerStore } from '../stores/galleryPlayerStore'
import { useAppStore } from '../stores/appStore'
import toast from 'react-hot-toast'
import { appLog } from '../lib/appLogger'
import { GALLERY_METADATA_JOB_PREFIX } from '../constants/jobPrefixes'

export const GalleryThumb: React.FC<{ sources: string[]; className?: string }> = ({ sources, className }) => {
  const [sourceIndex, setSourceIndex] = useState(0)

  useEffect(() => {
    setSourceIndex(0)
  }, [sources])

  const src = sources[sourceIndex] || null

  if (!src) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-space-800">
        <Image className="h-8 w-8 text-space-500" />
      </div>
    )
  }

  return (
    <img
      src={src}
      alt=""
      className={className || 'h-full w-full object-cover'}
      loading="lazy"
      referrerPolicy={src.startsWith('https:') ? 'no-referrer' : undefined}
      onError={() => {
        if (sourceIndex < sources.length - 1) {
          setSourceIndex((current) => current + 1)
        }
      }}
    />
  )
}

type GallerySortKey =
  | 'scrapedAt'
  | 'duration'
  | 'uploadDate'
  | 'views'
  | 'likes'
  | 'dislikes'
  | 'storage'
  | 'title'
  | 'channel'

const GALLERY_SORT_OPTIONS: { value: GallerySortKey; label: string }[] = [
  { value: 'scrapedAt', label: 'Date/time scraped' },
  { value: 'duration', label: 'Video length' },
  { value: 'uploadDate', label: 'Video upload date' },
  { value: 'views', label: 'Views' },
  { value: 'likes', label: 'Likes' },
  { value: 'dislikes', label: 'Dislikes' },
  { value: 'storage', label: 'Storage usage' },
  { value: 'title', label: 'Title' },
  { value: 'channel', label: 'Channel' },
]

const GALLERY_SORT_KEY_SET = new Set<GallerySortKey>(GALLERY_SORT_OPTIONS.map((o) => o.value))

function galleryTieBreak(a: VideoResult, b: VideoResult): number {
  const at = Date.parse(a.scrapedAt) || 0
  const bt = Date.parse(b.scrapedAt) || 0
  if (bt !== at) {
    return bt - at
  }
  return a.videoId.localeCompare(b.videoId)
}

function pickNumericSortValue(result: VideoResult, key: GallerySortKey): number | null {
  switch (key) {
    case 'duration':
      return result.durationSeconds
    case 'views':
      return result.viewCount
    case 'likes':
      return result.likeCount
    case 'dislikes':
      return result.dislikeCount
    case 'storage':
      return result.folderSizeBytes
    default:
      return null
  }
}

function compareGalleryResults(a: VideoResult, b: VideoResult, sortKey: GallerySortKey, sortDir: 'asc' | 'desc'): number {
  const orient = (n: number) => (sortDir === 'asc' ? n : -n)

  switch (sortKey) {
    case 'scrapedAt': {
      const at = Date.parse(a.scrapedAt) || 0
      const bt = Date.parse(b.scrapedAt) || 0
      const c = at - bt
      return c !== 0 ? orient(c) : galleryTieBreak(a, b)
    }
    case 'duration':
    case 'views':
    case 'likes':
    case 'dislikes':
    case 'storage': {
      const nullRep = sortDir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY
      const av = pickNumericSortValue(a, sortKey) ?? nullRep
      const bv = pickNumericSortValue(b, sortKey) ?? nullRep
      if (av === bv) {
        return galleryTieBreak(a, b)
      }
      return orient(av < bv ? -1 : 1)
    }
    case 'uploadDate': {
      const nullRep = sortDir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY
      const av = a.publishedAtMs > 0 ? a.publishedAtMs : nullRep
      const bv = b.publishedAtMs > 0 ? b.publishedAtMs : nullRep
      if (av === bv) {
        return galleryTieBreak(a, b)
      }
      return orient(av < bv ? -1 : 1)
    }
    case 'title': {
      const c = a.title.localeCompare(b.title, undefined, { sensitivity: 'base' })
      return c !== 0 ? orient(c) : galleryTieBreak(a, b)
    }
    case 'channel': {
      const c = a.channelTitle.localeCompare(b.channelTitle, undefined, { sensitivity: 'base' })
      return c !== 0 ? orient(c) : galleryTieBreak(a, b)
    }
    default:
      return galleryTieBreak(a, b)
  }
}

function formatGalleryMetaNumber(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) {
    return '—'
  }
  return n.toLocaleString()
}

function formatGalleryMetaBytes(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n) || n < 0) {
    return '—'
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  const rounded = i === 0 ? Math.round(v) : v >= 10 ? Math.round(v) : Math.round(v * 10) / 10
  return `${rounded} ${units[i]}`
}

function formatGalleryPublished(iso: string | null, publishedAtMs: number): string {
  if (iso && iso.length > 0) {
    const ms = Date.parse(iso)
    if (Number.isFinite(ms)) {
      return new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    }
  }
  if (publishedAtMs > 0) {
    return new Date(publishedAtMs).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  }
  return '—'
}

function GalleryMetaItem({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="min-w-[4.5rem]">
      <p className="text-[10px] font-medium uppercase tracking-wide text-space-500">{label}</p>
      <p className="mt-0.5 break-all text-sm leading-snug text-space-100 sm:whitespace-nowrap sm:break-normal">{value}</p>
    </div>
  )
}

function formatFastApiDetail(raw: unknown): string {
  if (!raw || typeof raw !== 'object') {
    return ''
  }
  const detail = (raw as { detail?: unknown }).detail
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return JSON.stringify(item)
      })
      .join('; ')
  }
  return ''
}

function outputDirBasename(dir: string): string {
  const s = dir.replace(/\\/g, '/')
  const parts = s.split('/').filter(Boolean)
  return parts[parts.length - 1] || dir || '—'
}

function shortenGalleryLabel(label: string, maxChars: number): string {
  const t = label.trim()
  if (t.length <= maxChars) {
    return t
  }
  if (maxChars <= 1) {
    return '…'
  }
  return `${t.slice(0, maxChars - 1)}…`
}

/** ~5 stacked list rows before scroll; caps vertical growth vs. the player column. */
const GALLERY_LIST_MAX_HEIGHT_CLASS = 'max-h-[min(36rem,calc(100vh-14rem))]'

const MAX_METADATA_REFRESH_BATCH = 20


export interface VideoGalleryViewProps {
  /** Called after a batch placeholder job is created so Jobs can reflect in-progress gallery metadata refreshes. */
  onNavigateToJobs?: () => void
}

const VideoGalleryView: React.FC<VideoGalleryViewProps> = ({
  onNavigateToJobs,
}) => {
  const galleryDiskRevisionBump = useScrapeStore((s) => s.galleryDiskRevisionBump)
  const bumpGalleryDiskRevision = useScrapeStore((s) => s.bumpGalleryDiskRevision)
  const { jobs, removeJobsByOutputDir, addJob, updateJob, setPendingAutoExpandJobId, addJobLog } =
    useScrapeStore()
  const results = useVideoResults(jobs, galleryDiskRevisionBump)
  const { serverUrl, isServerRunning, checkServerStatus } = useAppStore()
  const setActiveMedia = useGalleryPlayerStore((s) => s.setActiveMedia)
  const setPlaybackProgress = useGalleryPlayerStore((s) => s.setPlaybackProgress)
  const markPlaybackStarted = useGalleryPlayerStore((s) => s.markPlaybackStarted)
  const clearPlayback = useGalleryPlayerStore((s) => s.clearPlayback)
  const storedMediaPath = useGalleryPlayerStore((s) => s.mediaPath)
  const mediaVolume = useGalleryPlayerStore((s) => s.mediaVolume)
  const setMediaVolume = useGalleryPlayerStore((s) => s.setMediaVolume)
  const galleryVideoRef = useRef<HTMLVideoElement | null>(null)
  const galleryAudioRef = useRef<HTMLAudioElement | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [sortKey, setSortKey] = useState<GallerySortKey>('scrapedAt')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null)
  const [mediaFiles, setMediaFiles] = useState<MediaFileInfo[]>([])
  const [selectedMediaPath, setSelectedMediaPath] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [isMetadataRefreshing, setIsMetadataRefreshing] = useState(false)
  const [metadataToolsOpen, setMetadataToolsOpen] = useState(false)
  const [bulkDeleteToolsOpen, setBulkDeleteToolsOpen] = useState(false)
  const isSelectionMode = metadataToolsOpen || bulkDeleteToolsOpen

  useEffect(() => {
    void checkServerStatus()
  }, [checkServerStatus])

  useEffect(() => {
    if (!metadataToolsOpen && !bulkDeleteToolsOpen) {
      setSelectedIds(new Set())
    }
  }, [metadataToolsOpen, bulkDeleteToolsOpen])

  useEffect(() => {
    const valid = new Set(results.map((r) => r.id))
    setSelectedIds((prev) => {
      let dropped = false
      for (const id of prev) {
        if (!valid.has(id)) {
          dropped = true
          break
        }
      }
      if (!dropped) {
        return prev
      }
      const next = new Set<string>()
      for (const id of prev) {
        if (valid.has(id)) {
          next.add(id)
        }
      }
      return next
    })
  }, [results])

  const filteredResults = useMemo(() => {
    const query = searchQuery.toLowerCase().trim()
    let next = [...results]
    if (query) {
      next = next.filter(
        (result) =>
          result.title.toLowerCase().includes(query) ||
          result.channelTitle.toLowerCase().includes(query) ||
          result.videoId.toLowerCase().includes(query)
      )
    }
    next.sort((a, b) => compareGalleryResults(a, b, sortKey, sortDir))
    return next
  }, [results, searchQuery, sortKey, sortDir])

  const toggleRowSelected = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const selectAllVisible = useCallback(() => {
    setSelectedIds(new Set(filteredResults.map((r) => r.id)))
  }, [filteredResults])

  const clearRowSelection = useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  const toggleMetadataTools = useCallback(() => {
    setMetadataToolsOpen((open) => {
      const next = !open
      if (next) {
        setBulkDeleteToolsOpen(false)
      }
      return next
    })
  }, [])

  const toggleBulkDeleteTools = useCallback(() => {
    setBulkDeleteToolsOpen((open) => {
      const next = !open
      if (next) {
        setMetadataToolsOpen(false)
      }
      return next
    })
  }, [])

  const handleBulkDeleteSelected = async () => {
    const selected = results.filter((r) => selectedIds.has(r.id))
    if (selected.length === 0) {
      if (selectedIds.size > 0) {
        toast.error('Selection does not match loaded results. Try clearing selection and selecting again.')
      } else {
        toast.error('Select at least one video')
      }
      return
    }
    if (
      !confirm(
        `Delete ${selected.length} scrape folder(s) from disk and remove them from the list?\n\nThis cannot be undone.`
      )
    ) {
      return
    }
    if (!window.electronAPI?.deleteOutputScrapeDir) {
      toast.error('Delete is not available in this environment')
      return
    }
    let ok = 0
    let failed = 0
    for (const result of selected) {
      const r = await window.electronAPI.deleteOutputScrapeDir(result.outputDir)
      if (!r.ok) {
        failed++
        appLog('warn', 'VideoGallery', 'bulk_delete_folder_failed', {
          outputDir: result.outputDir,
          error: r.error,
        })
        continue
      }
      removeJobsByOutputDir(result.outputDir)
      ok++
      if (selectedResultId === result.id) {
        setSelectedResultId(null)
      }
      if (
        storedMediaPath &&
        (storedMediaPath.startsWith(result.outputDir.replace(/\\/g, '/')) ||
          storedMediaPath.includes(result.outputDir))
      ) {
        clearPlayback()
      }
    }
    setSelectedIds(new Set())
    if (ok > 0) {
      bumpGalleryDiskRevision()
      toast.success(`Deleted ${ok} folder${ok === 1 ? '' : 's'}${failed ? ` (${failed} failed)` : ''}`)
    }
    if (failed > 0 && ok === 0) {
      toast.error(`Could not delete ${failed} folder(s). Check logs or permissions.`)
    } else if (failed > 0) {
      toast.error(`${failed} folder(s) could not be deleted`, { duration: 4000 })
    }
  }

  const handleRefreshMetadata = async () => {
    if (!isServerRunning || !serverUrl) {
      toast.error('API server is not running')
      appLog('warn', 'VideoGallery', 'metadata_refresh_skipped_no_server')
      return
    }
    const selected = results.filter((r) => selectedIds.has(r.id))
    if (selected.length === 0) {
      if (selectedIds.size > 0) {
        toast.error('Selection does not match loaded results. Try clearing selection and selecting again.')
        appLog('error', 'VideoGallery', 'metadata_refresh_selection_mismatch', {
          selectedIdCount: selectedIds.size,
        })
      } else {
        toast.error('Select at least one video')
      }
      return
    }
    if (selected.length > MAX_METADATA_REFRESH_BATCH) {
      toast.error(`Select at most ${MAX_METADATA_REFRESH_BATCH} videos per batch`)
      return
    }
    const loadingId = toast.loading(`Refreshing metadata for ${selected.length} video(s)…`)
    appLog('info', 'VideoGallery', 'metadata_refresh_request', {
      count: selected.length,
      serverUrl,
    })

    const refreshJobId = `${GALLERY_METADATA_JOB_PREFIX}${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`}`
    addJob(
      {
        id: refreshJobId,
        url:
          selected.length === 1
            ? selected[0].url
            : `${selected.length} selected videos`,
        launchCaption: 'Gallery - Metadata refresh',
        videoTitle: selected.length === 1 ? selected[0].title : `${selected.length} videos`,
        status: 'running',
        progress: 12,
        type: 'video',
        operations: ['video'],
        startedAt: new Date().toISOString(),
      },
      { skipDashboardBump: true }
    )
    addJobLog(refreshJobId, {
      level: 'info',
      message: `Starting batch (${selected.length} folder(s)); receiving live logs from /metadata/refresh-batch-stream.`,
      timestamp: new Date().toISOString(),
    })
    setPendingAutoExpandJobId(refreshJobId)
    onNavigateToJobs?.()

    setIsMetadataRefreshing(true)
    try {
      updateJob(refreshJobId, { progress: 16 })
      const bodyPayload = JSON.stringify({
        items: selected.map((r) => ({ output_dir: r.outputDir, url: r.url })),
      })
      const response = await fetch(`${serverUrl}/metadata/refresh-batch-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: bodyPayload,
      })
      let errRaw: unknown = {}
      if (!response.ok) {
        try {
          errRaw = await response.json()
        } catch {
          try {
            errRaw = { detail: await response.text() }
          } catch {
            errRaw = {}
          }
        }
        const msg = formatFastApiDetail(errRaw) || response.statusText
        appLog('error', 'VideoGallery', 'metadata_refresh_http_error', {
          status: response.status,
          msg,
          raw: errRaw,
        })
        throw new Error(msg || `Request failed (${response.status})`)
      }
      if (!response.body) {
        throw new Error('Metadata refresh stream unavailable (empty body). Restart the API or update the app.')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let sawDone = false
      let rowResults: Array<{ output_dir: string; ok: boolean; error?: string | null }> = []
      let streamOutputRoots: string[] | undefined

      const mapDoneResults = (
        rows: Array<Record<string, unknown>>
      ): Array<{ output_dir: string; ok: boolean; error?: string | null }> =>
        rows.map((row) => ({
          output_dir: String(row.output_dir ?? ''),
          ok: Boolean(row.ok),
          error:
            row.error === null || row.error === undefined
              ? null
              : typeof row.error === 'string'
                ? row.error
                : String(row.error),
        }))

      const ingestDoneEnvelope = (ev: Record<string, unknown>) => {
        sawDone = true
        if (Array.isArray(ev.output_roots)) {
          streamOutputRoots = ev.output_roots as string[]
        }
        const rr = ev.results
        if (Array.isArray(rr)) {
          rowResults = mapDoneResults(rr as Array<Record<string, unknown>>)
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          break
        }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const rawLine of lines) {
          const line = rawLine.trim()
          if (!line) {
            continue
          }
          let ev: Record<string, unknown>
          try {
            ev = JSON.parse(line) as Record<string, unknown>
          } catch {
            continue
          }
          switch (ev.type) {
            case 'start': {
              updateJob(refreshJobId, { progress: 17 })
              break
            }
            case 'item': {
              const total =
                typeof ev.total === 'number' && ev.total > 0 ? ev.total : selected.length
              const idxRaw =
                typeof ev.index === 'number' && Number.isFinite(ev.index) ? Number(ev.index) : 0
              const idx = Math.max(0, Math.floor(idxRaw))
              const rowSel = selected[idx]
              const folderLeaf = outputDirBasename(
                typeof ev.output_dir === 'string'
                  ? ev.output_dir
                  : rowSel?.outputDir ?? '?'
              )
              const titleHint = shortenGalleryLabel(rowSel?.title ?? '(no title)', 56)
              const okEv = Boolean(ev.ok)
              const detailErr =
                ev.error !== null && ev.error !== undefined ? String(ev.error) : ''
              const detailShort = shortenGalleryLabel(detailErr, 360)
              const lineMsg = okEv
                ? `[${idx + 1}/${total}] OK · ${folderLeaf}: ${titleHint}`
                : `[${idx + 1}/${total}] Failed · ${folderLeaf}: ${detailShort}`
              addJobLog(refreshJobId, {
                level: okEv ? 'info' : 'warn',
                message: lineMsg,
                timestamp: new Date().toISOString(),
              })
              {
                const pct =
                  total > 0 ? Math.min(94, 8 + Math.round(((idx + 1) / total) * 86)) : 50
                updateJob(refreshJobId, { progress: pct })
              }
              break
            }
            case 'done': {
              ingestDoneEnvelope(ev)
              break
            }
            default:
              break
          }
        }
      }

      const tail = buffer.trim()
      if (!sawDone && tail.length > 0) {
        try {
          const ev = JSON.parse(tail) as Record<string, unknown>
          if (ev.type === 'done') {
            ingestDoneEnvelope(ev)
          }
        } catch {
          /* incomplete JSON — fall through */
        }
      }

      if (!sawDone) {
        throw new Error('Incomplete metadata refresh stream from server.')
      }

      if (rowResults.length === 0) {
        updateJob(refreshJobId, {
          status: 'failed',
          progress: 100,
          error: 'Server returned no per-item results',
          completedAt: new Date().toISOString(),
        })
        toast.error('Server returned no per-item results. Check application logs.')
        appLog('error', 'VideoGallery', 'metadata_refresh_empty_results', {})
        return
      }
      if (rowResults.length !== selected.length) {
        appLog('warn', 'VideoGallery', 'metadata_refresh_result_count_mismatch', {
          expected: selected.length,
          got: rowResults.length,
        })
      }
      const okCount = rowResults.filter((r) => r.ok).length
      const failCount = rowResults.length - okCount
      addJobLog(refreshJobId, {
        level: 'info',
        message: `Batch finished: ${okCount} succeeded, ${failCount} failed (${rowResults.length} total).`,
        timestamp: new Date().toISOString(),
      })
      appLog('info', 'VideoGallery', 'metadata_refresh_response', {
        okCount,
        failCount,
        outputRoots: streamOutputRoots,
      })
      if (okCount > 0) {
        bumpGalleryDiskRevision()
      }
      if (failCount === 0) {
        updateJob(refreshJobId, {
          status: 'completed',
          progress: 100,
          completedAt: new Date().toISOString(),
        })
        toast.success(
          `Metadata refreshed for ${okCount} video${okCount === 1 ? '' : 's'}. Updates appear on Gallery and Jobs.`,
          { duration: 5200 }
        )
      } else if (okCount > 0) {
        updateJob(refreshJobId, {
          status: 'completed',
          progress: 100,
          completedAt: new Date().toISOString(),
          warnings: rowResults
            .filter((r) => !r.ok)
            .slice(0, 20)
            .map((r) => ({
              operation: 'video',
              error: `${r.output_dir}${r.error ? `: ${r.error}` : ''}`,
            })),
        })
        toast.success(
          `Refreshed ${okCount} of ${rowResults.length}. ${failCount} failed.`,
          { duration: 5200 }
        )
        for (const row of rowResults.filter((r) => !r.ok).slice(0, 3)) {
          toast.error(row.error || row.output_dir, { duration: 4500 })
        }
      } else {
        updateJob(refreshJobId, {
          status: 'failed',
          progress: 100,
          completedAt: new Date().toISOString(),
          error: 'Metadata refresh failed for all selected items',
        })
        toast.error('Metadata refresh failed for all selected items')
        for (const row of rowResults.slice(0, 3)) {
          toast.error(row.error || row.output_dir, { duration: 4500 })
        }
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Metadata refresh failed'
      updateJob(refreshJobId, {
        status: 'failed',
        progress: 100,
        completedAt: new Date().toISOString(),
        error: message,
      })
      toast.error(message)
      appLog('error', 'VideoGallery', 'metadata_refresh_exception', { message: String(message) })
    } finally {
      toast.dismiss(loadingId)
      setIsMetadataRefreshing(false)
    }
  }

  const handleSortKeyChange = (value: string) => {
    if (!GALLERY_SORT_KEY_SET.has(value as GallerySortKey)) {
      return
    }
    const key = value as GallerySortKey
    setSortKey(key)
    if (key === 'title' || key === 'channel') {
      setSortDir('asc')
    } else {
      setSortDir('desc')
    }
  }

  const selectedResult = filteredResults.find((result) => result.id === selectedResultId) || filteredResults[0] || null
  const selectedMedia = mediaFiles.find((file) => file.path === selectedMediaPath) || mediaFiles[0] || null
  const resolvedSelectionId = selectedResult?.id ?? null

  const lastActiveMediaKeyRef = useRef<string>('')

  useEffect(() => {
    if (!resolvedSelectionId) {
      setSelectedResultId(null)
      return
    }
    if (selectedResultId !== resolvedSelectionId) {
      setSelectedResultId(resolvedSelectionId)
    }
  }, [resolvedSelectionId, selectedResultId])

  useEffect(() => {
    const dir = selectedResult?.outputDir
    if (!dir || !window.electronAPI) {
      setMediaFiles([])
      setSelectedMediaPath(null)
      return
    }

    let cancelled = false

    void window.electronAPI.listOutputMediaFiles(dir).then((files) => {
      if (cancelled) {
        return
      }
      const nextFiles = (files as MediaFileInfo[]) || []
      setMediaFiles(nextFiles)
      setSelectedMediaPath(nextFiles[0]?.path || null)
    })

    return () => {
      cancelled = true
    }
  }, [selectedResult?.outputDir])

  useEffect(() => {
    if (!selectedResult || !selectedMedia) {
      lastActiveMediaKeyRef.current = ''
      return
    }
    const key = [
      selectedResult.id,
      selectedMedia.path,
      selectedMedia.type,
      selectedResult.thumbnailSources.join('|'),
    ].join('\0')
    if (lastActiveMediaKeyRef.current === key) {
      return
    }
    lastActiveMediaKeyRef.current = key
    setActiveMedia(selectedMedia.path, selectedMedia.type, selectedResult.thumbnailSources)
  }, [
    selectedResult,
    selectedMedia,
    setActiveMedia,
  ])

  useEffect(() => {
    if (selectedMedia?.type === 'video' && galleryVideoRef.current) {
      galleryVideoRef.current.volume = mediaVolume
    }
    if (selectedMedia?.type === 'audio' && galleryAudioRef.current) {
      galleryAudioRef.current.volume = mediaVolume
    }
  }, [selectedMedia?.path, selectedMedia?.type, mediaVolume])

  const handleDeleteResult = async (result: VideoResult) => {
    if (
      !confirm(
        `Delete this scrape folder from disk and remove it from the list?\n\n${result.outputDir}`
      )
    ) {
      return
    }
    if (window.electronAPI?.deleteOutputScrapeDir) {
      const r = await window.electronAPI.deleteOutputScrapeDir(result.outputDir)
      if (!r.ok) {
        window.alert(r.error ?? 'Could not delete folder')
        return
      }
    }
    removeJobsByOutputDir(result.outputDir)
    if (selectedResultId === result.id) {
      setSelectedResultId(null)
    }
    if (
      storedMediaPath &&
      (storedMediaPath.startsWith(result.outputDir.replace(/\\/g, '/')) ||
        storedMediaPath.includes(result.outputDir))
    ) {
      clearPlayback()
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-2xl font-display font-bold text-white">Video Gallery</h2>
          <p className="text-space-400">Browse scraped videos and play downloaded media</p>
        </div>
        <div className="flex flex-shrink-0 flex-wrap items-center justify-start gap-2 sm:justify-end">
          {selectedResult ? (
            <button
              type="button"
              onClick={() => window.electronAPI?.showItemInFolder(selectedResult.outputDir)}
              className="futuristic-btn flex items-center gap-2"
            >
              <FolderOpen className="h-4 w-4" />
              Open Selected Folder
            </button>
          ) : null}
          {results.length > 0 ? (
            <>
              <button
                type="button"
                role="switch"
                aria-checked={metadataToolsOpen}
                onClick={toggleMetadataTools}
                title={
                  metadataToolsOpen
                    ? 'Hide metadata tools and row checkboxes'
                    : 'Show Refresh metadata, selection, and row checkboxes'
                }
                className={`futuristic-btn flex items-center gap-2 border transition-colors ${
                  metadataToolsOpen
                    ? 'border-neon-blue/50 bg-neon-blue/15 text-neon-blue'
                    : 'border-white/10'
                }`}
              >
                Metadata
              </button>
              <button
                type="button"
                role="switch"
                aria-checked={bulkDeleteToolsOpen}
                aria-label={
                  bulkDeleteToolsOpen
                    ? 'Close bulk delete selection'
                    : 'Open bulk delete selection'
                }
                onClick={toggleBulkDeleteTools}
                title={
                  bulkDeleteToolsOpen
                    ? 'Hide bulk delete tools and row checkboxes'
                    : 'Select folders to delete from disk and job list'
                }
                className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border transition-colors ${
                  bulkDeleteToolsOpen
                    ? 'border-rose-500/65 bg-rose-500/20 text-rose-400'
                    : 'border-white/10 text-rose-400/90 hover:border-rose-500/40 hover:bg-rose-500/10'
                }`}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </>
          ) : null}
        </div>
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch lg:gap-4">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-space-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search videos by title, channel, or video ID..."
            className="futuristic-input w-full !pl-14 py-3 pr-4"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
          <span className="text-sm text-space-400 whitespace-nowrap">Sort by</span>
          <select
            value={sortKey}
            onChange={(e) => handleSortKeyChange(e.target.value)}
            aria-label="Sort gallery list"
            className="futuristic-input min-w-[12rem] py-2.5 pr-8"
          >
            {GALLERY_SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
            className="futuristic-btn flex h-11 w-11 shrink-0 items-center justify-center border border-white/10 p-0"
            title={
              sortDir === 'asc'
                ? 'Ascending — click to sort descending'
                : 'Descending — click to sort ascending'
            }
            aria-label={sortDir === 'asc' ? 'Sort descending' : 'Sort ascending'}
          >
            {sortDir === 'asc' ? (
              <ArrowUpNarrowWide className="h-4 w-4" />
            ) : (
              <ArrowDownWideNarrow className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>

      {metadataToolsOpen && filteredResults.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void handleRefreshMetadata()}
            disabled={
              !isServerRunning ||
              selectedIds.size === 0 ||
              isMetadataRefreshing ||
              selectedIds.size > MAX_METADATA_REFRESH_BATCH
            }
            className="futuristic-btn flex items-center gap-2 disabled:opacity-40"
            title={
              !isServerRunning
                ? 'Start the API server to refresh metadata'
                : selectedIds.size > MAX_METADATA_REFRESH_BATCH
                  ? `Select at most ${MAX_METADATA_REFRESH_BATCH} videos`
                  : 'Re-scrape YouTube metadata into the selected folders'
            }
          >
            <RefreshCw className={`h-4 w-4 ${isMetadataRefreshing ? 'animate-spin' : ''}`} />
            {isMetadataRefreshing ? 'Refreshing…' : 'Refresh metadata'}
          </button>
          <button type="button" onClick={selectAllVisible} className="futuristic-btn text-sm">
            Select all visible
          </button>
          <button
            type="button"
            onClick={clearRowSelection}
            disabled={selectedIds.size === 0}
            className="futuristic-btn text-sm disabled:opacity-40"
          >
            Clear selection
          </button>
          {selectedIds.size > 0 ? (
            <span className="text-sm text-space-400">
              {selectedIds.size} selected
              {selectedIds.size > MAX_METADATA_REFRESH_BATCH
                ? ` (max ${MAX_METADATA_REFRESH_BATCH} per batch)`
                : ''}
            </span>
          ) : null}
        </div>
      ) : null}

      {bulkDeleteToolsOpen && filteredResults.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-rose-500/25 bg-rose-500/[0.06] px-3 py-2">
          <button type="button" onClick={selectAllVisible} className="futuristic-btn text-sm">
            Select all visible
          </button>
          <button
            type="button"
            onClick={clearRowSelection}
            disabled={selectedIds.size === 0}
            className="futuristic-btn text-sm disabled:opacity-40"
          >
            Clear selection
          </button>
          <button
            type="button"
            onClick={() => void handleBulkDeleteSelected()}
            disabled={selectedIds.size === 0}
            className="futuristic-btn flex items-center gap-2 border border-rose-500/40 bg-rose-500/15 text-sm text-rose-200 disabled:opacity-40"
            title="Permanently delete selected scrape folders from disk"
          >
            <Trash2 className="h-4 w-4" />
            Delete selected
          </button>
          {selectedIds.size > 0 ? (
            <span className="text-sm text-rose-200/80">{selectedIds.size} selected</span>
          ) : null}
        </div>
      ) : null}

      {filteredResults.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <div className="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-full bg-space-800">
            <Video className="h-10 w-10 text-space-400" />
          </div>
          <h3 className="mb-2 text-xl font-semibold text-white">No Videos Yet</h3>
          <p className="text-space-400">
            {searchQuery ? 'No videos match your search' : 'Complete a scrape to populate the gallery'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-12 items-start gap-6">
          <div className={`col-span-5 xl:col-span-4 ${GALLERY_LIST_MAX_HEIGHT_CLASS} space-y-3 overflow-y-auto overflow-x-hidden pr-1`}>
            {filteredResults.map((result) => {
              const isSelected = selectedResult?.id === result.id
              return (
                <div
                  key={`${result.videoId}-${result.outputDir}`}
                  className={`glass-card w-full overflow-hidden transition-all ${
                    isSelected ? 'border-neon-blue/60 bg-neon-blue/10' : ''
                  }`}
                >
                  <div className="flex gap-1 p-2 sm:gap-2 sm:p-3">
                    {isSelectionMode ? (
                      <label className="flex shrink-0 cursor-pointer items-start pt-2">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(result.id)}
                          onChange={() => toggleRowSelected(result.id)}
                          onClick={(e) => e.stopPropagation()}
                          className={`mt-0.5 h-4 w-4 rounded border-glass-border bg-space-900 focus:ring-neon-blue/40 ${
                            bulkDeleteToolsOpen
                              ? 'text-rose-500 focus:ring-rose-500/40'
                              : 'text-neon-blue'
                          }`}
                          aria-label={
                            bulkDeleteToolsOpen
                              ? `Select for delete: ${result.title}`
                              : `Select for metadata refresh: ${result.title}`
                          }
                        />
                      </label>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => setSelectedResultId(result.id)}
                      className={`flex min-w-0 flex-1 gap-3 rounded-lg p-1 text-left transition-colors ${
                        isSelected ? '' : 'hover:bg-white/[0.04]'
                      }`}
                    >
                      <div className="h-20 w-32 flex-shrink-0 overflow-hidden rounded-lg bg-space-800">
                        <GalleryThumb sources={result.thumbnailSources} />
                      </div>
                      <div className="min-w-0 flex-1 py-0.5">
                        <h3 className="truncate font-medium text-white">{result.title}</h3>
                        <p className="truncate text-sm text-space-400">{result.channelTitle}</p>
                        <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-space-500">
                          <span className="font-mono">{result.videoId}</span>
                          {result.commentCount != null && Number.isFinite(result.commentCount) ? (
                            <span className="text-space-400">
                              {result.commentCount.toLocaleString()} comments
                            </span>
                          ) : null}
                        </p>
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDeleteResult(result)}
                      className="flex h-10 w-10 flex-shrink-0 items-center justify-center self-center rounded-lg text-space-400 transition-colors hover:bg-rose-500/10 hover:text-rose-400 sm:self-stretch sm:h-auto sm:w-11"
                      title="Delete scrape folder"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>

          <div className="col-span-7 xl:col-span-8">
            <div className="glass-card overflow-hidden">
              <div className="aspect-video bg-black">
                {selectedResult && selectedMedia?.type === 'video' && window.electronAPI ? (
                  <video
                    key={selectedMedia.path}
                    ref={galleryVideoRef}
                    className="h-full w-full"
                    controls
                    playsInline
                    preload="metadata"
                    src={window.electronAPI.getAppMediaUrl(selectedMedia.path)}
                    onVolumeChange={(e) => setMediaVolume(e.currentTarget.volume)}
                    onTimeUpdate={(e) => {
                      const v = e.currentTarget
                      setPlaybackProgress(v.currentTime, !v.paused && !v.ended)
                    }}
                    onPlay={(e) => {
                      markPlaybackStarted()
                      const v = e.currentTarget
                      setPlaybackProgress(v.currentTime, true)
                    }}
                    onPause={(e) => {
                      const v = e.currentTarget
                      setPlaybackProgress(v.currentTime, false)
                    }}
                    onLoadedMetadata={(e) => {
                      const v = e.currentTarget
                      const st = useGalleryPlayerStore.getState()
                      v.volume = st.mediaVolume
                      const { resumeSeconds: t, resumeShouldPlay: play } = st
                      if (t > 0.05 && (Number.isFinite(v.duration) ? t < v.duration : true)) {
                        v.currentTime = t
                      }
                      if (play) {
                        void v.play().catch(() => {})
                      }
                    }}
                  />
                ) : selectedResult && selectedMedia?.type === 'audio' && window.electronAPI ? (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-8">
                    <div className="h-48 w-80 overflow-hidden rounded-lg bg-space-800">
                      <GalleryThumb sources={selectedResult.thumbnailSources} />
                    </div>
                    <audio
                      key={selectedMedia.path}
                      ref={galleryAudioRef}
                      className="w-full max-w-2xl"
                      controls
                      preload="metadata"
                      src={window.electronAPI.getAppMediaUrl(selectedMedia.path)}
                      onVolumeChange={(e) => setMediaVolume(e.currentTarget.volume)}
                      onTimeUpdate={(e) => {
                        const a = e.currentTarget
                        setPlaybackProgress(a.currentTime, !a.paused && !a.ended)
                      }}
                      onPlay={(e) => {
                        markPlaybackStarted()
                        const a = e.currentTarget
                        setPlaybackProgress(a.currentTime, true)
                      }}
                      onPause={(e) => {
                        const a = e.currentTarget
                        setPlaybackProgress(a.currentTime, false)
                      }}
                      onLoadedMetadata={(e) => {
                        const a = e.currentTarget
                        const st = useGalleryPlayerStore.getState()
                        a.volume = st.mediaVolume
                        const { resumeSeconds: t, resumeShouldPlay: play } = st
                        if (t > 0.05 && (Number.isFinite(a.duration) ? t < a.duration : true)) {
                          a.currentTime = t
                        }
                        if (play) {
                          void a.play().catch(() => {})
                        }
                      }}
                    />
                  </div>
                ) : selectedResult ? (
                  <GalleryThumb sources={selectedResult.thumbnailSources} className="h-full w-full object-cover opacity-80" />
                ) : null}
              </div>

              <div className="space-y-4 p-5">
                <div className="flex flex-col gap-4 rounded-xl border border-glass-border bg-white/[0.04] px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-xl font-semibold leading-snug text-white">
                      {selectedResult?.title || 'Select a video'}
                    </h3>
                    <p className="mt-1 text-space-400">
                      {selectedResult?.channelTitle || 'Choose a scraped result from the gallery'}
                    </p>
                  </div>
                  {selectedResult ? (
                    <div className="flex min-h-[6.5rem] min-w-0 flex-shrink-0 flex-col gap-3 sm:max-w-[58%] sm:items-end">
                      <div className="flex w-full flex-wrap justify-start gap-x-6 gap-y-3 sm:justify-end">
                        <GalleryMetaItem
                          label="Publish date"
                          value={formatGalleryPublished(selectedResult.publishedAt, selectedResult.publishedAtMs)}
                        />
                        <GalleryMetaItem label="Likes" value={formatGalleryMetaNumber(selectedResult.likeCount)} />
                        <GalleryMetaItem label="Dislikes" value={formatGalleryMetaNumber(selectedResult.dislikeCount)} />
                      </div>
                      <div className="flex w-full flex-col gap-3 border-t border-white/[0.08] pt-3 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
                        <GalleryMetaItem label="Views" value={formatGalleryMetaNumber(selectedResult.viewCount)} />
                        <div className="flex flex-wrap gap-x-6 gap-y-2 sm:justify-end">
                          <GalleryMetaItem
                            label="Comments"
                            value={
                              selectedResult.commentCount != null
                                ? formatGalleryMetaNumber(selectedResult.commentCount)
                                : '—'
                            }
                          />
                          <GalleryMetaItem
                            label="File size"
                            value={formatGalleryMetaBytes(selectedMedia?.sizeBytes)}
                          />
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>

                {selectedResult && mediaFiles.length === 0 ? (
                  <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-sm text-amber-200">
                    No downloaded video file was found for this scrape. Enable Download Media on a scrape to play it here.
                  </div>
                ) : null}

                {mediaFiles.length > 1 ? (
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-white">Available media files</p>
                    <div className="grid gap-2">
                      {mediaFiles.map((file) => (
                        <button
                          key={file.path}
                          type="button"
                          onClick={() => setSelectedMediaPath(file.path)}
                          className={`rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                            selectedMedia?.path === file.path
                              ? 'bg-neon-blue/20 text-white'
                              : 'bg-white/5 text-space-300 hover:bg-white/[0.07] hover:text-white'
                          }`}
                        >
                          {file.name}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default VideoGalleryView
