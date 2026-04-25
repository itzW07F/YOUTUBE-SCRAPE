import React, { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { FolderOpen, Image, Search, Video } from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'
import { MediaFileInfo, useVideoResults, VideoResult } from '../hooks/useVideoResults'

const GalleryThumb: React.FC<{ sources: string[]; className?: string }> = ({ sources, className }) => {
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

function sortByScrapedAtDesc(a: VideoResult, b: VideoResult): number {
  return b.scrapedAt.localeCompare(a.scrapedAt)
}

const VideoGalleryView: React.FC = () => {
  const { jobs } = useScrapeStore()
  const results = useVideoResults(jobs)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null)
  const [mediaFiles, setMediaFiles] = useState<MediaFileInfo[]>([])
  const [selectedMediaPath, setSelectedMediaPath] = useState<string | null>(null)

  const filteredResults = useMemo(() => {
    const query = searchQuery.toLowerCase().trim()
    const sorted = [...results].sort(sortByScrapedAtDesc)
    if (!query) {
      return sorted
    }
    return sorted.filter(
      (result) =>
        result.title.toLowerCase().includes(query) ||
        result.channelTitle.toLowerCase().includes(query) ||
        result.videoId.toLowerCase().includes(query)
    )
  }, [results, searchQuery])

  const selectedResult = filteredResults.find((result) => result.id === selectedResultId) || filteredResults[0] || null
  const selectedMedia = mediaFiles.find((file) => file.path === selectedMediaPath) || mediaFiles[0] || null

  useEffect(() => {
    if (!selectedResult) {
      setSelectedResultId(null)
      return
    }
    if (selectedResultId !== selectedResult.id) {
      setSelectedResultId(selectedResult.id)
    }
  }, [selectedResult, selectedResultId])

  useEffect(() => {
    if (!selectedResult || !window.electronAPI) {
      setMediaFiles([])
      setSelectedMediaPath(null)
      return
    }

    let cancelled = false

    void window.electronAPI.listOutputMediaFiles(selectedResult.outputDir).then((files) => {
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
  }, [selectedResult])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-display font-bold text-white">Video Gallery</h2>
          <p className="text-space-400">Browse scraped videos and play downloaded media</p>
        </div>
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
      </div>

      <div className="relative">
        <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-space-400" />
        <input
          type="text"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search videos by title, channel, or video ID..."
          className="futuristic-input w-full py-3 pl-12 pr-4"
        />
      </div>

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
        <div className="grid grid-cols-12 gap-6">
          <div className="col-span-5 space-y-3 xl:col-span-4">
            {filteredResults.map((result) => {
              const isSelected = selectedResult?.id === result.id
              return (
                <motion.button
                  key={`${result.videoId}-${result.outputDir}`}
                  type="button"
                  layout
                  onClick={() => setSelectedResultId(result.id)}
                  className={`glass-card w-full overflow-hidden text-left transition-all ${
                    isSelected ? 'border-neon-blue/60 bg-neon-blue/10' : 'hover:bg-white/[0.07]'
                  }`}
                >
                  <div className="flex gap-3 p-3">
                    <div className="h-20 w-32 flex-shrink-0 overflow-hidden rounded-lg bg-space-800">
                      <GalleryThumb sources={result.thumbnailSources} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <h3 className="truncate font-medium text-white">{result.title}</h3>
                      <p className="truncate text-sm text-space-400">{result.channelTitle}</p>
                      <p className="mt-2 text-xs text-space-500">{result.videoId}</p>
                    </div>
                  </div>
                </motion.button>
              )
            })}
          </div>

          <div className="col-span-7 xl:col-span-8">
            <div className="glass-card overflow-hidden">
              <div className="aspect-video bg-black">
                {selectedResult && selectedMedia?.type === 'video' && window.electronAPI ? (
                  <video
                    key={selectedMedia.path}
                    className="h-full w-full"
                    controls
                    playsInline
                    preload="metadata"
                    src={window.electronAPI.getAppMediaUrl(selectedMedia.path)}
                  />
                ) : selectedResult && selectedMedia?.type === 'audio' && window.electronAPI ? (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-8">
                    <div className="h-48 w-80 overflow-hidden rounded-lg bg-space-800">
                      <GalleryThumb sources={selectedResult.thumbnailSources} />
                    </div>
                    <audio
                      key={selectedMedia.path}
                      className="w-full max-w-2xl"
                      controls
                      preload="metadata"
                      src={window.electronAPI.getAppMediaUrl(selectedMedia.path)}
                    />
                  </div>
                ) : selectedResult ? (
                  <GalleryThumb sources={selectedResult.thumbnailSources} className="h-full w-full object-cover opacity-80" />
                ) : null}
              </div>

              <div className="space-y-4 p-5">
                <div>
                  <h3 className="text-xl font-semibold text-white">{selectedResult?.title || 'Select a video'}</h3>
                  <p className="text-space-400">{selectedResult?.channelTitle || 'Choose a scraped result from the gallery'}</p>
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
