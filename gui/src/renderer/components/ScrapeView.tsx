import React, { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Play,
  Youtube,
  MessageSquare,
  FileText,
  Image,
  Download,
  Settings2,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Check,
} from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'
import toast from 'react-hot-toast'

type ScrapeOperation = 'video' | 'comments' | 'transcript' | 'thumbnails' | 'download'
type AppView = 'dashboard' | 'scrape' | 'jobs' | 'results' | 'gallery' | 'settings' | 'debug'

interface ScrapeViewProps {
  onNavigate: (view: AppView) => void
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
  return operations.length > 0 ? operations : ['video']
}

const ScrapeView: React.FC<ScrapeViewProps> = ({ onNavigate }) => {
  const [url, setUrl] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  
  const { scrapeOptions, updateScrapeOptions, addJob, setActiveJob } = useScrapeStore()
  const { serverUrl, isServerRunning } = useAppStore()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    
    const normalized = normalizeYoutubeInput(url)
    if (!normalized) {
      toast.error('Please enter a valid YouTube URL or video ID')
      return
    }

    if (!isServerRunning || !serverUrl) {
      toast.error('API server is not running')
      return
    }

    setIsSubmitting(true)

    try {
      // Build the scrape request
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
          transcript_format: scrapeOptions.transcriptFormat,
          video_quality: scrapeOptions.videoQuality,
        }),
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to start scrape')
      }

      const data = await response.json()
      
      const operations = selectedOperations(scrapeOptions)

      // Add job to store
      addJob({
        id: data.job_id,
        url: normalized,
        status: 'running',
        progress: 0,
        type: operations.length === 1 ? operations[0] : 'all',
        operations,
        outputDir: data.output_dir,
        startedAt: new Date().toISOString(),
      })

      setActiveJob(data.job_id)
      toast.success('Scrape job started!')
      setUrl('')
      onNavigate('jobs')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to start scrape')
    } finally {
      setIsSubmitting(false)
    }
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

  return (
    <div className="max-w-3xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card gradient-border p-8"
      >
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-neon-blue to-neon-purple flex items-center justify-center">
            <Play className="w-6 h-6 text-white" />
          </div>
          <div>
            <h2 className="text-2xl font-display font-bold text-white">New Scrape</h2>
            <p className="text-space-400">Enter a YouTube URL or video ID to begin extraction</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* URL Input */}
          <div>
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
                  <div>
                    <label className="block text-sm text-space-300 mb-2">
                      Max Comments
                    </label>
                    <input
                      type="number"
                      value={scrapeOptions.maxComments}
                      onChange={(e) => updateScrapeOptions({ maxComments: parseInt(e.target.value) || 100 })}
                      min={1}
                      max={10000}
                      className="futuristic-input w-32"
                    />
                  </div>
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
          <div className="pt-4">
            <button
              type="submit"
              disabled={isSubmitting || !url || !isValidYoutubeInput(url) || !isServerRunning}
              className={`
                w-full py-4 rounded-xl font-semibold text-lg flex items-center justify-center gap-2
                ${isSubmitting || !url || !isValidYoutubeInput(url) || !isServerRunning
                  ? 'bg-space-700 text-space-400 cursor-not-allowed'
                  : 'futuristic-btn futuristic-btn-primary'
                }
              `}
            >
              {isSubmitting ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Starting Scrape...
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  Start Scraping
                </>
              )}
            </button>
            
            {!isServerRunning && (
              <p className="mt-3 text-sm text-rose-400 text-center">
                API server is not running. Please wait for it to start.
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
