import React, { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { FolderOpen, Image, Search, Trash2, Video } from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'
import { MediaFileInfo, useVideoResults, VideoResult } from '../hooks/useVideoResults'
import { useGalleryPlayerStore } from '../stores/galleryPlayerStore'

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

function sortByScrapedAtDesc(a: VideoResult, b: VideoResult): number {
  return b.scrapedAt.localeCompare(a.scrapedAt)
}

const VideoGalleryView: React.FC = () => {
  const { jobs, removeJobsByOutputDir } = useScrapeStore()
  const results = useVideoResults(jobs)
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

  useEffect(() => {
    if (!selectedResult || !selectedMedia) {
      return
    }
    setActiveMedia(selectedMedia.path, selectedMedia.type, selectedResult.thumbnailSources)
  }, [
    selectedResult?.id,
    selectedMedia?.path,
    selectedMedia?.type,
    selectedResult?.thumbnailSources,
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
          className="futuristic-input w-full !pl-14 py-3 pr-4"
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
                <motion.div
                  key={`${result.videoId}-${result.outputDir}`}
                  layout
                  className={`glass-card w-full overflow-hidden transition-all ${
                    isSelected ? 'border-neon-blue/60 bg-neon-blue/10' : ''
                  }`}
                >
                  <div className="flex gap-1 p-2 sm:gap-2 sm:p-3">
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
                        <p className="mt-2 text-xs text-space-500">{result.videoId}</p>
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
                </motion.div>
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
