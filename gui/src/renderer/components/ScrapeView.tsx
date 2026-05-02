import React, { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Play,
  Youtube,
  MessageSquare,
  FileText,
  Image,
  Download,
  Layers,
  Settings2,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Check,
  ListOrdered,
} from 'lucide-react'
import { useScrapeStore, buildLaunchCaptionForJobStart, type ScrapeQuickPreset } from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'
import toast from 'react-hot-toast'

type ScrapeOperation = 'video' | 'comments' | 'transcript' | 'thumbnails' | 'download'
type AppView =
  | 'dashboard'
  | 'scrape'
  | 'jobs'
  | 'results'
  | 'gallery'
  | 'analytics'
  | 'settings'
  | 'debug'

interface ScrapeViewProps {
  onNavigate: (view: AppView, options?: { preserveScrapeOptions?: boolean }) => void
}

function selectedOperations(options: ReturnType<typeof useScrapeStore.getState>['scrapeOptions']): ScrapeOperation[] {
  const operations: ScrapeOperation[] = []
  if (options.includeVideo) {
    operations.push('video')
  }
  if (options.includeComments) {
    operations.push('comments')
  }
  if (options.includeTranscript) {
    operations.push('transcript')
  }
  if (options.includeThumbnails) {
    operations.push('thumbnails')
  }
  if (options.includeDownload) {
    operations.push('download')
  }
  return operations
}

function isAllScrapeTargetsOn(
  options: ReturnType<typeof useScrapeStore.getState>['scrapeOptions']
): boolean {
  return (
    options.includeVideo &&
    options.includeComments &&
    options.includeTranscript &&
    options.includeThumbnails &&
    options.includeDownload
  )
}

const ScrapeView: React.FC<ScrapeViewProps> = ({ onNavigate }) => {
  const [url, setUrl] = useState('')
  const [batchMode, setBatchMode] = useState(false)
  const [batchText, setBatchText] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  
  const {
    scrapeOptions,
    updateScrapeOptions,
    applyScrapePreset,
    resetScrapeTogglesToNone,
    addJob,
    setActiveJob,
    setPendingAutoExpandJobId,
    setPendingDashboardQuickPreset,
  } = useScrapeStore()
  const { serverUrl, isServerRunning } = useAppStore()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!isServerRunning || !serverUrl) {
      toast.error('API server is not running')
      return
    }

    const operations = selectedOperations(scrapeOptions)
    if (operations.length === 0) {
      toast.error('Select at least one scrape target')
      return
    }

    if (!batchMode) {
      const normalized = normalizeYoutubeInput(url)
      if (!normalized) {
        toast.error('Please enter a valid YouTube URL or video ID')
        return
      }
      setIsSubmitting(true)
      try {
        await startScrapeForUrl(normalized, { quiet: false })
        setUrl('')
        onNavigate('jobs')
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to start scrape')
      } finally {
        setIsSubmitting(false)
      }
      return
    }

    const rawPieces = extractBatchYoutubeEntries(batchText)
    const normalizedUrls: string[] = []
    const invalidPieces: string[] = []
    for (const raw of rawPieces) {
      const trimmed = raw.trim()
      const n = normalizeYoutubeInput(trimmed)
      if (n) {
        normalizedUrls.push(n)
      } else if (trimmed && !trimmed.startsWith('#')) {
        invalidPieces.push(trimmed)
      }
    }
    const unique = [...new Set(normalizedUrls)]

    if (unique.length === 0) {
      toast.error(
        invalidPieces.length
          ? `No valid entries (${invalidPieces.length} invalid)`
          : 'Add at least one URL or ID per line (# starts a comment line)'
      )
      return
    }

    setIsSubmitting(true)
    const batchDashPreset = useScrapeStore.getState().pendingDashboardQuickPreset
    const isMultiBatch = unique.length > 1
    try {
      let ok = 0
      let fail = 0
      let lastFailure: Error | null = null
      for (const normalized of unique) {
        try {
          await startScrapeForUrl(normalized, {
            quiet: true,
            dashboardQuickPreset: batchDashPreset,
            isBatch: isMultiBatch,
          })
          ok++
        } catch (error) {
          fail++
          lastFailure = error instanceof Error ? error : new Error(String(error))
        }
      }

      const isFull = isAllScrapeTargetsOn(scrapeOptions)
      if (ok === 1 && fail === 0) {
        toast.success(isFull ? 'Full scrape started!' : 'Scrape job started!')
      } else if (fail === 0) {
        toast.success(`Queued ${ok} scrape job${ok === 1 ? '' : 's'}`)
      } else if (ok === 0) {
        toast.error(lastFailure?.message ?? 'Could not queue any scrape jobs')
      } else {
        toast(
          `${ok} job${ok === 1 ? '' : 's'} queued, ${fail} failed.${lastFailure ? ` Last: ${lastFailure.message}` : ''}`
        )
      }

      if (invalidPieces.length > 0) {
        toast(`${invalidPieces.length} entr${invalidPieces.length === 1 ? 'y' : 'ies'} skipped (invalid format)`)
      }

      setBatchText('')
      onNavigate('jobs')
    } finally {
      setPendingDashboardQuickPreset(null)
      setIsSubmitting(false)
    }
  }

  const startScrapeForUrl = async (
    normalized: string,
    options?: {
      quiet?: boolean
      /** When set for batch runs: same preset for every row; store pending is not read. */
      dashboardQuickPreset?: ScrapeQuickPreset | null
      isBatch?: boolean
    }
  ) => {
    if (!serverUrl) {
      throw new Error('API server is not running')
    }

    const response = await fetch(`${serverUrl}/scrape/video`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: normalized,
        include_video: scrapeOptions.includeVideo,
        include_comments: scrapeOptions.includeComments,
        include_transcript: scrapeOptions.includeTranscript,
        include_thumbnails: scrapeOptions.includeThumbnails,
        include_download: scrapeOptions.includeDownload,
        max_comments: scrapeOptions.maxComments,
        max_replies_per_thread: scrapeOptions.maxRepliesPerThread,
        transcript_format: scrapeOptions.transcriptFormat,
        video_quality: scrapeOptions.videoQuality,
      }),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error((error as { detail?: string }).detail || 'Failed to start scrape')
    }

    const data = (await response.json()) as { job_id?: string; output_dir?: string }
    const jobId = String(data.job_id ?? '')
    const outputDir = data.output_dir
    if (!jobId || typeof outputDir !== 'string') {
      throw new Error('Invalid response when starting scrape')
    }

    const operations = selectedOperations(scrapeOptions)
    const isFull = isAllScrapeTargetsOn(scrapeOptions)
    const isBatch = options?.isBatch ?? false
    const store = useScrapeStore.getState()
    const presetFromCaller = options?.dashboardQuickPreset
    const dashboardQuickPreset =
      presetFromCaller !== undefined ? presetFromCaller : store.pendingDashboardQuickPreset
    const launchCaption = buildLaunchCaptionForJobStart({
      dashboardQuickPreset,
      isBatch,
      operations,
    })
    if (presetFromCaller === undefined && !isBatch) {
      setPendingDashboardQuickPreset(null)
    }

    addJob({
      id: jobId,
      url: normalized,
      status: 'running',
      progress: 0,
      type: operations.length === 1 ? operations[0] : 'all',
      operations,
      outputDir,
      launchCaption,
      startedAt: new Date().toISOString(),
    })

    setActiveJob(jobId)
    setPendingAutoExpandJobId(jobId)

    if (!options?.quiet) {
      toast.success(isFull ? 'Full scrape started!' : 'Scrape job started!')
    }

    return { jobId, outputDir }
  }

  const toggleOption = (key: keyof typeof scrapeOptions) => {
    updateScrapeOptions({ [key]: !scrapeOptions[key as keyof typeof scrapeOptions] })
  }

  const scrapeTypes = [
    { key: 'includeVideo', label: 'Video Metadata', icon: Youtube, description: 'Title, channel, views, duration, etc.' },
    { key: 'includeComments', label: 'Comments', icon: MessageSquare, description: 'Comments and replies' },
    { key: 'includeTranscript', label: 'Transcript', icon: FileText, description: 'Auto-generated or manual captions' },
    { key: 'includeThumbnails', label: 'Thumbnails', icon: Image, description: 'All available thumbnail sizes' },
    { key: 'includeDownload', label: 'Download Media', icon: Download, description: 'Video or audio file' },
  ]

  const fullScrapeActive = isAllScrapeTargetsOn(scrapeOptions)
  const hasScrapeTargets = selectedOperations(scrapeOptions).length > 0
  const singleReady = !!url.trim() && isValidYoutubeInput(url)
  const batchReady = !!batchText.trim()
  const canSubmit =
    isServerRunning &&
    hasScrapeTargets &&
    (batchMode ? batchReady : singleReady)

  return (
    <div className="max-w-3xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card gradient-border p-8"
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-neon-blue to-neon-purple flex items-center justify-center">
              <Play className="w-6 h-6 text-white" />
            </div>
            <div>
              <h2 className="text-2xl font-display font-bold text-white">New Scrape</h2>
              <p className="text-space-400">
                Single video or{' '}
                <span className="text-neon-cyan">batch list</span> — same options apply to each job.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              setBatchMode((b) => !b)
            }}
            className={`flex shrink-0 items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors ${
              batchMode
                ? 'border-neon-cyan/50 bg-neon-cyan/10 text-white'
                : 'border-glass-border bg-white/5 text-space-300 hover:bg-white/[0.07]'
            }`}
          >
            <ListOrdered className="h-4 w-4 text-neon-cyan" />
            {batchMode ? 'Batch mode on' : 'Batch URLs / IDs'}
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* URL or batch list */}
          <div>
            {!batchMode ? (
              <>
                <label className="block text-sm font-medium text-space-200 mb-2">
                  YouTube URL or video ID
                </label>
                <div className="relative">
                  <Youtube className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-space-400" />
                  <input
                    type="text"
                    inputMode="url"
                    autoComplete="off"
                    spellCheck={false}
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://www.youtube.com/watch?v=… or dQw4w9WgXcQ"
                    className="futuristic-input w-full !pl-14 pr-4 py-4 text-lg"
                    disabled={isSubmitting}
                  />
                </div>
                {url && !isValidYoutubeInput(url) && (
                  <p className="mt-2 text-sm text-rose-400 flex items-center gap-1">
                    <AlertCircle className="w-4 h-4" />
                    Please enter a valid YouTube URL or video ID
                  </p>
                )}
              </>
            ) : (
              <>
                <label className="block text-sm font-medium text-space-200 mb-2">
                  Multiple URLs or video IDs
                </label>
                <textarea
                  value={batchText}
                  onChange={(e) => setBatchText(e.target.value)}
                  disabled={isSubmitting}
                  rows={10}
                  spellCheck={false}
                  placeholder={
                    `One per line — comments start with #\n\n` +
                    `https://www.youtube.com/watch?v=dQw4w9WgXcQ\n` +
                    `dQw4w9WgXcQ\n` +
                    `https://youtu.be/VIDEO_ID_HERE`
                  }
                  className="futuristic-input w-full min-h-[14rem] resize-y px-4 py-3 font-mono text-sm leading-relaxed"
                />
                <p className="mt-2 text-xs text-space-500">
                  Duplicates removed after normalization. Separate videos with commas on one line — they are split.
                </p>
              </>
            )}
          </div>

          {/* Scrape Options */}
          <div>
            <label className="block text-sm font-medium text-space-200 mb-3">
              What to Scrape
            </label>
            <div className="grid grid-cols-2 gap-3">
              {scrapeTypes.map((type) => {
                const Icon = type.icon
                const isActive = scrapeOptions[type.key as keyof typeof scrapeOptions] as boolean

                return (
                  <button
                    key={type.key}
                    type="button"
                    onClick={() => toggleOption(type.key as keyof typeof scrapeOptions)}
                    className={`
                      flex items-start gap-3 p-4 rounded-xl border transition-all text-left
                      ${isActive
                        ? 'bg-neon-blue/10 border-neon-blue/40 text-white'
                        : 'bg-white/5 border-glass-border text-space-300 hover:bg-white/[0.07]'
                      }
                    `}
                  >
                    <div className={`
                      w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0
                      ${isActive ? 'bg-neon-blue/20' : 'bg-space-700'}
                    `}>
                      <Icon className={`w-5 h-5 ${isActive ? 'text-neon-blue' : 'text-space-400'}`} />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{type.label}</span>
                        {isActive && <Check className="w-4 h-4 text-neon-blue" />}
                      </div>
                      <p className="text-xs text-space-400 mt-1">{type.description}</p>
                    </div>
                  </button>
                )
              })}
              <button
                type="button"
                onClick={() =>
                  fullScrapeActive ? resetScrapeTogglesToNone() : applyScrapePreset('all')
                }
                className={`
                  flex items-start gap-3 p-4 rounded-xl border transition-all text-left
                  ${fullScrapeActive
                    ? 'bg-neon-purple/10 border-neon-purple/40 text-white'
                    : 'bg-white/5 border-glass-border text-space-300 hover:bg-white/[0.07]'
                  }
                `}
                title={
                  fullScrapeActive
                    ? 'Clear all scrape targets'
                    : 'Select all scrape targets at once'
                }
              >
                <div
                  className={`
                  w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0
                  ${fullScrapeActive ? 'bg-neon-purple/20' : 'bg-space-700'}
                `}
                >
                  <Layers className={`w-5 h-5 ${fullScrapeActive ? 'text-neon-purple' : 'text-space-400'}`} />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">Full Scrape</span>
                    {fullScrapeActive && <Check className="w-4 h-4 text-neon-purple" />}
                  </div>
                  <p className="text-xs text-space-400 mt-1">All options above in one job</p>
                </div>
              </button>
            </div>
          </div>

          {/* Advanced Options */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-2 text-sm text-space-300 hover:text-white transition-colors"
            >
              <Settings2 className="w-4 h-4" />
              Advanced Options
              {showAdvanced ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>

            {showAdvanced && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                className="mt-4 p-4 rounded-xl bg-white/5 border border-glass-border space-y-4"
              >
                {scrapeOptions.includeComments && (
                  <p className="text-sm text-space-400">
                    Comment volume and per-thread reply limits are configured in{' '}
                    <span className="text-neon-cyan">Settings</span> (Comment scraping).
                  </p>
                )}

                {scrapeOptions.includeTranscript && (
                  <div>
                    <label className="block text-sm text-space-300 mb-2">
                      Transcript Format
                    </label>
                    <select
                      value={scrapeOptions.transcriptFormat}
                      onChange={(e) => updateScrapeOptions({ transcriptFormat: e.target.value as 'txt' | 'vtt' | 'json' })}
                      className="futuristic-input w-40"
                    >
                      <option value="txt">Plain Text (.txt)</option>
                      <option value="vtt">WebVTT (.vtt)</option>
                      <option value="json">JSON (.json)</option>
                    </select>
                  </div>
                )}

                {scrapeOptions.includeDownload && (
                  <div>
                    <label className="block text-sm text-space-300 mb-2">
                      Video Quality
                    </label>
                    <select
                      value={scrapeOptions.videoQuality}
                      onChange={(e) => updateScrapeOptions({ videoQuality: e.target.value })}
                      className="futuristic-input w-48"
                    >
                      <option value="best">Best Available</option>
                      <option value="1080">1080p</option>
                      <option value="720">720p</option>
                      <option value="480">480p</option>
                      <option value="audio">Audio Only</option>
                    </select>
                  </div>
                )}
              </motion.div>
            )}
          </div>

          {/* Submit Button */}
          <div className="pt-4 space-y-3">
            <button
              type="submit"
              disabled={isSubmitting || !canSubmit}
              className={`
                w-full py-4 rounded-xl font-semibold text-lg flex items-center justify-center gap-2
                ${isSubmitting || !canSubmit
                  ? 'bg-space-700 text-space-400 cursor-not-allowed'
                  : 'futuristic-btn futuristic-btn-primary'
                }
              `}
            >
              {isSubmitting ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  {batchMode ? 'Queuing jobs…' : 'Starting Scrape…'}
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  {batchMode ? 'Start batch scrape' : 'Start Scraping'}
                </>
              )}
            </button>
            {!isServerRunning && (
              <p className="text-sm text-rose-400 text-center">
                API server is not running. Please wait for it to start.
              </p>
            )}
            {isServerRunning && !batchMode && url && isValidYoutubeInput(url) && !hasScrapeTargets && (
              <p className="text-sm text-amber-200/90 text-center">
                Choose at least one target under What to Scrape
              </p>
            )}
            {isServerRunning && batchMode && batchReady && !hasScrapeTargets && (
              <p className="text-sm text-amber-200/90 text-center">
                Choose at least one target under What to Scrape
              </p>
            )}
          </div>
        </form>
      </motion.div>
    </div>
  )
}

/** YouTube video IDs are 11 characters from [A-Za-z0-9_-]. */
const YOUTUBE_VIDEO_ID = /^[a-zA-Z0-9_-]{11}$/

/**
 * Browsers often copy host-only paths (no scheme). Prepend https:// for known YouTube hosts
 * without treating bare 11-char video IDs as URLs.
 */
function withHttpsSchemeIfNeeded(trimmed: string): string {
  if (!trimmed || /^https?:\/\//i.test(trimmed)) {
    return trimmed
  }
  if (YOUTUBE_VIDEO_ID.test(trimmed)) {
    return trimmed
  }
  const lower = trimmed.toLowerCase()
  if (
    lower.startsWith('www.') ||
    lower.includes('youtube.com') ||
    lower.includes('youtu.be')
  ) {
    return `https://${trimmed}`
  }
  return trimmed
}

/** Expand pasted batch textarea: newline-separated rows; commas split IDs on one line; # begins comment. */
function extractBatchYoutubeEntries(raw: string): string[] {
  const out: string[] = []
  for (const segment of raw.split(/[\r\n]+/)) {
    const line = segment.trim()
    if (!line || line.startsWith('#')) {
      continue
    }
    const pieces = line.includes(',')
      ? line.split(',').map((p) => p.trim()).filter(Boolean)
      : [line]
    for (const p of pieces) {
      if (!p || p.startsWith('#')) {
        continue
      }
      out.push(withHttpsSchemeIfNeeded(p))
    }
  }
  return out
}

function isValidYoutubeUrl(s: string): boolean {
  const trimmed = withHttpsSchemeIfNeeded(s.trim())
  const patterns = [
    /^https?:\/\/(www\.)?youtube\.com\/watch\?v=[\w-]+/,
    /^https?:\/\/youtu\.be\/[\w-]+/,
    /^https?:\/\/(www\.)?youtube\.com\/shorts\/[\w-]+/,
    /^https?:\/\/(www\.)?youtube\.com\/live\/[\w-]+/,
  ]
  return patterns.some((pattern) => pattern.test(trimmed))
}

function isValidYoutubeInput(s: string): boolean {
  const t = s.trim()
  return isValidYoutubeUrl(t) || YOUTUBE_VIDEO_ID.test(t)
}

/** Returns a canonical watch URL, or null if the input is not a supported URL or bare video ID. */
function normalizeYoutubeInput(s: string): string | null {
  const t = s.trim()
  if (!t) {
    return null
  }
  if (YOUTUBE_VIDEO_ID.test(t)) {
    return `https://www.youtube.com/watch?v=${t}`
  }
  if (!isValidYoutubeUrl(t)) {
    return null
  }
  return withHttpsSchemeIfNeeded(t)
}

export default ScrapeView
