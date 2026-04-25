import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  FolderOpen,
  Search,
  FileJson,
  FileText,
  Image,
  Video,
  ChevronRight,
  ChevronDown,
} from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'
import { useVideoResults, VideoResult } from '../hooks/useVideoResults'

type ArtifactKind = 'video' | 'comments' | 'transcript' | 'thumbnails' | 'media' | 'summary'

interface OutputArtifactRead {
  kind: ArtifactKind
  fileName: string | null
  contentType: 'json' | 'text' | 'images' | 'media'
  content: string | null
  truncated: boolean
  images: Array<{ name: string; path: string }>
  media: Array<{ name: string; path: string; type: 'video' | 'audio' }>
}

const ResultsView: React.FC = () => {
  const { jobs } = useScrapeStore()
  const { outputDirectory } = useAppStore()
  const results = useVideoResults(jobs)
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const filteredResults = results.filter(
    (r) =>
      r.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.channelTitle.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.videoId.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleOpenFolder = (path: string) => {
    window.electronAPI?.showItemInFolder(path)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-display font-bold text-white">Results</h2>
          <p className="text-space-400">Browse and manage your scraped data</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => outputDirectory && handleOpenFolder(outputDirectory)}
            className="futuristic-btn flex items-center gap-2"
          >
            <FolderOpen className="w-4 h-4" />
            Open Output Folder
          </button>
        </div>
      </div>

      <div className="relative">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-space-400" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search by title, channel, or video ID..."
          className="futuristic-input w-full pl-12 pr-4 py-3"
        />
      </div>

      {filteredResults.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <div className="w-20 h-20 rounded-full bg-space-800 flex items-center justify-center mx-auto mb-4">
            <FolderOpen className="w-10 h-10 text-space-400" />
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">No Results Yet</h3>
          <p className="text-space-400">
            {searchQuery ? 'No results match your search' : 'Complete a scrape to see results here'}
          </p>
        </div>
      ) : (
        <div className="grid gap-4">
          {filteredResults.map((result) => (
            <ResultCard
              key={result.videoId}
              result={result}
              isExpanded={expandedId === result.videoId}
              onToggle={() => setExpandedId(expandedId === result.videoId ? null : result.videoId)}
              onOpenFolder={() => handleOpenFolder(result.outputDir)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface ResultCardProps {
  result: VideoResult
  isExpanded: boolean
  onToggle: () => void
  onOpenFolder: () => void
}

const ResultThumb: React.FC<{ sources: string[] }> = ({ sources }) => {
  const [sourceIndex, setSourceIndex] = useState(0)

  useEffect(() => {
    setSourceIndex(0)
  }, [sources])

  const src = sources[sourceIndex] || null

  if (!src) {
    return <Image className="w-6 h-6 text-space-500" />
  }

  const isHttps = src.startsWith('https:')

  return (
    <img
      src={src}
      alt=""
      className="w-full h-full object-cover"
      loading="lazy"
      referrerPolicy={isHttps ? 'no-referrer' : undefined}
      onError={() => {
        if (sourceIndex < sources.length - 1) {
          setSourceIndex((current) => current + 1)
        }
      }}
    />
  )
}

const ResultCard: React.FC<ResultCardProps> = ({ result, isExpanded, onToggle, onOpenFolder }) => {
  const [activeArtifact, setActiveArtifact] = useState<ArtifactKind | null>(null)
  const [artifact, setArtifact] = useState<OutputArtifactRead | null>(null)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [isArtifactLoading, setIsArtifactLoading] = useState(false)

  const fileTypes = [
    { key: 'hasVideo', kind: 'video', label: 'Video Data', icon: FileJson, ext: 'video.json' },
    { key: 'hasComments', kind: 'comments', label: 'Comments', icon: FileText, ext: 'comments.json' },
    { key: 'hasTranscript', kind: 'transcript', label: 'Transcript', icon: FileText, ext: 'transcript.*' },
    { key: 'hasThumbnails', kind: 'thumbnails', label: 'Thumbnails', icon: Image, ext: 'thumbnails/' },
    { key: 'hasDownload', kind: 'media', label: 'Media Files', icon: Video, ext: 'download/' },
    { key: 'hasVideo', kind: 'summary', label: 'Summary', icon: FileJson, ext: 'summary.json' },
  ] as const

  useEffect(() => {
    if (!isExpanded) {
      setActiveArtifact(null)
      setArtifact(null)
      return
    }
  }, [isExpanded])

  useEffect(() => {
    if (!isExpanded || !activeArtifact || !window.electronAPI) {
      return
    }

    let cancelled = false
    setIsArtifactLoading(true)
    setArtifactError(null)

    void window.electronAPI
      .readOutputArtifact(result.outputDir, activeArtifact)
      .then((nextArtifact) => {
        if (cancelled) {
          return
        }
        if (!nextArtifact) {
          setArtifact(null)
          setArtifactError('No artifact was found for this data type.')
          return
        }
        setArtifact(nextArtifact as OutputArtifactRead)
      })
      .catch((error) => {
        if (!cancelled) {
          setArtifact(null)
          setArtifactError(error instanceof Error ? error.message : 'Failed to read artifact.')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsArtifactLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [activeArtifact, isExpanded, result.outputDir])

  return (
    <motion.div
      layout
      className="glass-card overflow-hidden"
    >
      <div
        className="p-4 flex items-center gap-4 cursor-pointer hover:bg-white/[0.02] transition-colors"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && onToggle()}
      >
        <div className="w-24 h-16 rounded-lg overflow-hidden bg-space-800 flex-shrink-0 flex items-center justify-center">
          <ResultThumb sources={result.thumbnailSources} />
        </div>

        <div className="flex-1 min-w-0">
          <h3 className="text-white font-medium truncate">{result.title}</h3>
          <p className="text-sm text-space-400">{result.channelTitle}</p>
          <p className="text-xs text-space-500 mt-1">
            {result.videoId} • {new Date(result.scrapedAt).toLocaleString()}
          </p>
        </div>

        <div className="flex gap-2">
          {fileTypes.map((type) => {
            if (!result[type.key as keyof VideoResult]) {
              return null
            }
            const Icon = type.icon
            return (
              <div
                key={type.key}
                className="w-8 h-8 rounded-lg bg-space-700 flex items-center justify-center"
                title={type.label}
              >
                <Icon className="w-4 h-4 text-neon-blue" />
              </div>
            )
          })}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onOpenFolder()
            }}
            className="p-2 rounded-lg hover:bg-white/10 text-space-400 hover:text-white transition-colors"
            title="Open folder"
          >
            <FolderOpen className="w-4 h-4" />
          </button>
          <div className="p-2 text-space-400">
            {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </div>
        </div>
      </div>

      {isExpanded && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          className="border-t border-glass-border p-4 space-y-4"
        >
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {fileTypes.map((type) => {
              if (!result[type.key as keyof VideoResult]) {
                return null
              }
              const Icon = type.icon
              const isActive = activeArtifact === type.kind

              return (
                <button
                  key={type.kind}
                  type="button"
                  onClick={() => setActiveArtifact(isActive ? null : type.kind)}
                  className={`flex items-center gap-3 p-3 rounded-lg transition-colors text-left group ${
                    isActive ? 'bg-neon-blue/15 border border-neon-blue/30' : 'bg-white/5 hover:bg-white/[0.07]'
                  }`}
                >
                  <div className="w-10 h-10 rounded-lg bg-neon-blue/10 flex items-center justify-center group-hover:bg-neon-blue/20 transition-colors">
                    <Icon className="w-5 h-5 text-neon-blue" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white">{type.label}</p>
                    <p className="text-xs text-space-400 truncate">{type.ext}</p>
                  </div>
                  {isActive ? <ChevronDown className="w-4 h-4 text-neon-blue" /> : <ChevronRight className="w-4 h-4 text-space-500" />}
                </button>
              )
            })}
          </div>

          <ArtifactPanel
            artifact={artifact}
            error={artifactError}
            isLoading={isArtifactLoading}
            activeKind={activeArtifact}
          />

          <div className="pt-2 border-t border-glass-border">
            <p className="text-sm text-space-400 mb-2">Output Directory</p>
            <code className="code-block px-3 py-2 block text-xs text-space-300">
              {result.outputDir}
            </code>
          </div>
        </motion.div>
      )}
    </motion.div>
  )
}

interface ArtifactPanelProps {
  artifact: OutputArtifactRead | null
  error: string | null
  isLoading: boolean
  activeKind: ArtifactKind | null
}

function formatArtifactContent(artifact: OutputArtifactRead): string {
  if (!artifact.content) {
    return ''
  }

  if (artifact.contentType !== 'json') {
    return artifact.content
  }

  try {
    return JSON.stringify(JSON.parse(artifact.content), null, 2)
  } catch {
    return artifact.content
  }
}

const ArtifactPanel: React.FC<ArtifactPanelProps> = ({ artifact, error, isLoading, activeKind }) => {
  if (!activeKind) {
    return (
      <div className="rounded-xl border border-dashed border-glass-border bg-white/[0.03] p-8 text-center">
        <FileText className="mx-auto mb-3 h-8 w-8 text-space-500" />
        <p className="text-sm text-space-400">Select a scraped data type above to preview it here.</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="rounded-xl bg-space-900/60 p-8 text-center">
        <div className="mx-auto mb-3 h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-neon-blue" />
        <p className="text-sm text-space-400">Loading scraped data...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-200">
        {error}
      </div>
    )
  }

  if (!artifact) {
    return null
  }

  if (artifact.contentType === 'images') {
    return (
      <div className="space-y-4 rounded-xl bg-space-900/60 p-4">
        <ArtifactHeader artifact={artifact} />
        {artifact.images.length > 0 ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {artifact.images.map((image) => (
              <div key={image.path} className="overflow-hidden rounded-lg bg-space-800">
                <img
                  src={window.electronAPI.getAppMediaUrl(image.path)}
                  alt={image.name}
                  className="aspect-video w-full object-cover"
                  loading="lazy"
                />
                <p className="truncate px-2 py-1 text-xs text-space-400">{image.name}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-space-400">No thumbnail image files were found.</p>
        )}
        {artifact.content ? <CodePreview content={formatArtifactContent(artifact)} truncated={artifact.truncated} /> : null}
      </div>
    )
  }

  if (artifact.contentType === 'media') {
    return (
      <div className="space-y-4 rounded-xl bg-space-900/60 p-4">
        <ArtifactHeader artifact={artifact} />
        {artifact.media.length > 0 ? (
          <div className="grid gap-2">
            {artifact.media.map((media) => (
              <div key={media.path} className="rounded-lg bg-white/5 p-3">
                <p className="text-sm text-white">{media.name}</p>
                <p className="text-xs uppercase tracking-wide text-neon-blue">{media.type}</p>
                <p className="mt-1 truncate font-mono text-xs text-space-500">{media.path}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-space-400">No downloaded media files were found.</p>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4 rounded-xl bg-space-900/60 p-4">
      <ArtifactHeader artifact={artifact} />
      <CodePreview content={formatArtifactContent(artifact)} truncated={artifact.truncated} />
    </div>
  )
}

const ArtifactHeader: React.FC<{ artifact: OutputArtifactRead }> = ({ artifact }) => (
  <div className="flex items-center justify-between gap-4 border-b border-glass-border pb-3">
    <div>
      <p className="text-sm font-medium capitalize text-white">{artifact.kind}</p>
      <p className="text-xs text-space-400">{artifact.fileName || 'Generated from output folder'}</p>
    </div>
    {artifact.truncated ? (
      <span className="rounded-full bg-amber-500/10 px-2 py-1 text-xs text-amber-200">
        Preview truncated
      </span>
    ) : null}
  </div>
)

const CodePreview: React.FC<{ content: string; truncated: boolean }> = ({ content, truncated }) => (
  <div>
    <pre className="max-h-[32rem] overflow-auto rounded-lg bg-black/40 p-4 text-xs leading-relaxed text-space-200">
      <code>{content || 'No content'}</code>
    </pre>
    {truncated ? (
      <p className="mt-2 text-xs text-amber-200">
        This file is large, so only the first 5 MB are shown.
      </p>
    ) : null}
  </div>
)

export default ResultsView
