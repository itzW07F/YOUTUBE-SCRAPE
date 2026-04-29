import React, { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  FolderOpen,
  Search,
  FileJson,
  FileText,
  Image,
  ChevronRight,
  ChevronDown,
  Trash2,
} from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'
import { useVideoResults, VideoResult } from '../hooks/useVideoResults'
import { StructuredArtifactPreview } from './ResultArtifactViews'

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
  const { jobs, removeJobsByOutputDir } = useScrapeStore()
  const bumpGalleryDiskRevision = useScrapeStore((s) => s.bumpGalleryDiskRevision)
  const { outputDirectory } = useAppStore()
  const galleryDiskRevisionBump = useScrapeStore((s) => s.galleryDiskRevisionBump)
  const results = useVideoResults(jobs, galleryDiskRevisionBump)
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [bulkDeleteToolsOpen, setBulkDeleteToolsOpen] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())

  useEffect(() => {
    if (!bulkDeleteToolsOpen) {
      setSelectedIds(new Set())
    }
  }, [bulkDeleteToolsOpen])

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

  const filteredResults = results.filter(
    r =>
      r.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.channelTitle.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.videoId.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleOpenFolder = (path: string) => {
    window.electronAPI?.showItemInFolder(path)
  }

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

  const handleBulkDeleteSelected = async () => {
    const selected = results.filter((r) => selectedIds.has(r.id))
    if (selected.length === 0) {
      if (selectedIds.size > 0) {
        window.alert('Selection does not match loaded results. Try clearing selection and selecting again.')
      } else {
        window.alert('Select at least one result')
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
      window.alert('Delete is not available in this environment')
      return
    }
    let ok = 0
    let failed = 0
    for (const result of selected) {
      const r = await window.electronAPI.deleteOutputScrapeDir(result.outputDir)
      if (!r.ok) {
        failed++
        continue
      }
      removeJobsByOutputDir(result.outputDir)
      ok++
      if (expandedId === result.videoId) {
        setExpandedId(null)
      }
    }
    setSelectedIds(new Set())
    if (ok > 0) {
      bumpGalleryDiskRevision()
    }
    if (failed > 0 && ok === 0) {
      window.alert(`Could not delete ${failed} folder(s). Check permissions or paths.`)
    } else if (failed > 0) {
      window.alert(`Deleted ${ok} folder(s). ${failed} could not be deleted.`)
    }
  }

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
    bumpGalleryDiskRevision()
    if (expandedId === result.videoId) {
      setExpandedId(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-display font-bold text-white">Results</h2>
          <p className="text-space-400">Browse and manage your scraped data</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {filteredResults.length > 0 ? (
            <button
              type="button"
              role="switch"
              aria-checked={bulkDeleteToolsOpen}
              aria-label={
                bulkDeleteToolsOpen ? 'Close bulk delete selection' : 'Open bulk delete selection'
              }
              onClick={() => setBulkDeleteToolsOpen((open) => !open)}
              title={
                bulkDeleteToolsOpen
                  ? 'Hide bulk delete and row checkboxes'
                  : 'Select folders to delete from disk'
              }
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border transition-colors ${
                bulkDeleteToolsOpen
                  ? 'border-rose-500/65 bg-rose-500/20 text-rose-400'
                  : 'border-white/10 text-rose-400/90 hover:border-rose-500/40 hover:bg-rose-500/10'
              }`}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          ) : null}
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
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search by title, channel, or video ID..."
          className="futuristic-input w-full !pl-14 pr-4 py-3"
        />
      </div>

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
          {filteredResults.map(result => (
            <ResultCard
              key={`${result.videoId}-${result.outputDir}`}
              result={result}
              isExpanded={expandedId === result.videoId}
              onToggle={() => setExpandedId(expandedId === result.videoId ? null : result.videoId)}
              onOpenFolder={() => handleOpenFolder(result.outputDir)}
              onDelete={() => void handleDeleteResult(result)}
              bulkSelectMode={bulkDeleteToolsOpen}
              rowSelected={selectedIds.has(result.id)}
              onToggleRowSelect={() => toggleRowSelected(result.id)}
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
  onDelete: () => void
  bulkSelectMode: boolean
  rowSelected: boolean
  onToggleRowSelect: () => void
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
          setSourceIndex(current => current + 1)
        }
      }}
    />
  )
}

const ResultCard: React.FC<ResultCardProps> = ({
  result,
  isExpanded,
  onToggle,
  onOpenFolder,
  onDelete,
  bulkSelectMode,
  rowSelected,
  onToggleRowSelect,
}) => {
  const [activeArtifact, setActiveArtifact] = useState<ArtifactKind | null>(null)
  const [artifact, setArtifact] = useState<OutputArtifactRead | null>(null)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [isArtifactLoading, setIsArtifactLoading] = useState(false)

  const fileTypes = [
    { key: 'hasVideo', kind: 'video', label: 'Video Data', icon: FileJson },
    {
      key: 'hasComments',
      kind: 'comments',
      label: 'Comments',
      icon: FileText,
    },
    {
      key: 'hasTranscript',
      kind: 'transcript',
      label: 'Transcript',
      icon: FileText,
    },
    {
      key: 'hasThumbnails',
      kind: 'thumbnails',
      label: 'Thumbnails',
      icon: Image,
    },
    { key: 'hasVideo', kind: 'summary', label: 'Summary', icon: FileJson },
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
      .then(nextArtifact => {
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
      .catch(error => {
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
    <motion.div layout="position" className="glass-card overflow-hidden">
      <div
        className="flex cursor-pointer flex-wrap items-start gap-4 p-4 hover:bg-white/[0.02] transition-colors md:flex-nowrap md:items-center"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && onToggle()}
      >
        {bulkSelectMode ? (
          <label className="flex shrink-0 cursor-pointer items-center self-center pt-1">
            <input
              type="checkbox"
              checked={rowSelected}
              onChange={onToggleRowSelect}
              onClick={e => e.stopPropagation()}
              className="h-4 w-4 rounded border-glass-border bg-space-900 text-rose-500 focus:ring-rose-500/40"
              aria-label={`Select for delete: ${result.title}`}
            />
          </label>
        ) : null}
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

        <div className="flex shrink-0 flex-col items-center gap-1.5">
          <span className="text-[10px] font-medium uppercase tracking-wide text-space-500">
            Data Points
          </span>
          <div className="flex gap-2">
            {fileTypes.map(type => {
              if (!result[type.key as keyof VideoResult]) {
                return null
              }
              const Icon = type.icon
              return (
                <div
                  key={type.kind}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-space-700"
                  title={type.label}
                >
                  <Icon className="h-4 w-4 text-neon-blue" />
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-center gap-1.5">
          <span className="text-[10px] font-medium uppercase tracking-wide text-space-500">
            Actions
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={e => {
                e.stopPropagation()
                onDelete()
              }}
              className="rounded-lg p-2 text-space-400 transition-colors hover:bg-rose-500/10 hover:text-rose-400"
              title="Delete scrape folder"
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={e => {
                e.stopPropagation()
                onOpenFolder()
              }}
              className="rounded-lg p-2 text-space-400 transition-colors hover:bg-white/10 hover:text-white"
              title="Open folder"
            >
              <FolderOpen className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="ml-auto flex shrink-0 self-center p-2 text-space-400 md:ml-0">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {isExpanded ? (
          <motion.div
            key="expanded-content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="min-w-0 overflow-hidden"
          >
            <div className="space-y-4 border-t border-glass-border p-4">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {fileTypes.map(type => {
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
                      className={`group flex min-w-0 items-center gap-2 rounded-lg p-2 text-left transition-colors ${
                        isActive
                          ? 'border border-neon-blue/30 bg-neon-blue/15'
                          : 'bg-white/5 hover:bg-white/[0.07]'
                      }`}
                    >
                      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-neon-blue/10 transition-colors group-hover:bg-neon-blue/20">
                        <Icon className="h-4 w-4 text-neon-blue" />
                      </div>
                      <p className="min-w-0 flex-1 text-[0.9375rem] font-medium leading-snug text-white">
                        {type.label}
                      </p>
                      {isActive ? (
                        <ChevronDown className="h-4 w-4 shrink-0 text-neon-blue" />
                      ) : (
                        <ChevronRight className="h-4 w-4 shrink-0 text-space-500" />
                      )}
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
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
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

/** Collapses single hard-wrapped newlines so prose reflows to the container; keeps blank-line gaps. */
function reflowHardWrappedLines(raw: string): string {
  const normalized = raw.replace(/\r\n/g, '\n')
  let prev = ''
  let cur = normalized
  while (prev !== cur) {
    prev = cur
    cur = cur.replace(/([^\n])\n([^\n])/g, '$1 $2')
  }
  return cur
}

const ArtifactPanel: React.FC<ArtifactPanelProps> = ({
  artifact,
  error,
  isLoading,
  activeKind,
}) => {
  if (!activeKind) {
    return (
      <div className="rounded-xl border border-dashed border-glass-border bg-white/[0.03] p-8 text-center">
        <FileText className="mx-auto mb-3 h-8 w-8 text-space-500" />
        <p className="text-sm text-space-400">
          Select a scraped data type above to preview it here.
        </p>
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
      <div className="min-w-0 w-full space-y-4 rounded-xl bg-space-900/60 p-4">
        <ArtifactHeader artifact={artifact} />
        {artifact.images.length > 0 ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {artifact.images.map(image => (
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
        {artifact.content ? (
          <StructuredArtifactPreview
            artifact={artifact}
            fallbackContent={formatArtifactContent(artifact)}
          />
        ) : null}
      </div>
    )
  }

  if (artifact.contentType === 'media') {
    return (
      <div className="space-y-4 rounded-xl bg-space-900/60 p-4">
        <ArtifactHeader artifact={artifact} />
        {artifact.media.length > 0 ? (
          <div className="grid gap-2">
            {artifact.media.map(media => (
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

  const plainTranscript = artifact.kind === 'transcript' && artifact.contentType === 'text'
  const useStructuredJson =
    artifact.contentType === 'json' &&
    (artifact.kind === 'video' ||
      artifact.kind === 'comments' ||
      artifact.kind === 'summary' ||
      artifact.kind === 'thumbnails')

  return (
    <div className="min-w-0 w-full space-y-4 rounded-xl bg-space-900/60 p-4">
      <ArtifactHeader artifact={artifact} />
      {plainTranscript ? (
        <CodePreview
          content={formatArtifactContent(artifact)}
          truncated={artifact.truncated}
          presentation="plain"
          reflowPlain
        />
      ) : useStructuredJson ? (
        <StructuredArtifactPreview
          artifact={artifact}
          fallbackContent={formatArtifactContent(artifact)}
        />
      ) : (
        <CodePreview
          content={formatArtifactContent(artifact)}
          truncated={artifact.truncated}
          presentation="json"
        />
      )}
    </div>
  )
}

const ArtifactHeader: React.FC<{ artifact: OutputArtifactRead }> = ({ artifact }) => (
  <div className="flex items-center justify-between gap-4 border-b border-glass-border pb-3">
    <div>
      <p className="text-sm font-medium capitalize text-white">{artifact.kind}</p>
      <p className="text-xs text-space-400">
        {artifact.fileName || 'Generated from output folder'}
      </p>
    </div>
    {artifact.truncated ? (
      <span className="rounded-full bg-amber-500/10 px-2 py-1 text-xs text-amber-200">
        Preview truncated
      </span>
    ) : null}
  </div>
)

interface CodePreviewProps {
  content: string
  truncated: boolean
  /** JSON stays monospace pre; transcript/plain uses wrapping full-width layout */
  presentation?: 'json' | 'plain'
  reflowPlain?: boolean
}

const CodePreview: React.FC<CodePreviewProps> = ({
  content,
  truncated,
  presentation = 'json',
  reflowPlain = false,
}) => {
  const raw = content || 'No content'
  const text = presentation === 'json' ? raw : reflowPlain ? reflowHardWrappedLines(raw) : raw

  return (
    <div className="min-w-0 w-full">
      <pre
        className={`max-h-[32rem] min-h-0 w-full min-w-0 overflow-auto rounded-lg bg-black/40 p-4 text-xs leading-relaxed text-space-200 ${
          presentation === 'plain' ? 'text-left' : ''
        }`}
      >
        <code
          className={`block w-full min-w-0 text-left font-mono ${
            presentation === 'plain' ? 'break-words whitespace-pre-wrap' : 'whitespace-pre'
          }`}
        >
          {text}
        </code>
      </pre>
      {truncated ? (
        <p className="mt-2 text-xs text-amber-200">
          This file is large, so only the first 5 MB are shown.
        </p>
      ) : null}
    </div>
  )
}

export default ResultsView
