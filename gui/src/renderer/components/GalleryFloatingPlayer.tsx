import React, { useEffect, useLayoutEffect, useRef } from 'react'
import { ChevronDown, ChevronUp, X } from 'lucide-react'
import { GalleryThumb } from './VideoGalleryView'
import { useGalleryPlayerStore } from '../stores/galleryPlayerStore'

interface GalleryFloatingPlayerProps {
  currentView: string
}

/** Off-screen clip region while collapsed; keeps media mounted for playback. */
function hiddenPlaybackShellClass(collapsed: boolean): string {
  return collapsed
    ? 'pointer-events-none fixed left-0 top-0 -z-10 h-[120px] w-[160px] opacity-0 overflow-hidden'
    : ''
}

export const GalleryFloatingPlayer: React.FC<GalleryFloatingPlayerProps> = ({ currentView }) => {
  const mediaPath = useGalleryPlayerStore((s) => s.mediaPath)
  const mediaKind = useGalleryPlayerStore((s) => s.mediaKind)
  const thumbnailSources = useGalleryPlayerStore((s) => s.thumbnailSources)
  const playbackStarted = useGalleryPlayerStore((s) => s.playbackStarted)
  const collapsed = useGalleryPlayerStore((s) => s.floatingPlayerCollapsed)
  const setPlaybackProgress = useGalleryPlayerStore((s) => s.setPlaybackProgress)
  const markPlaybackStarted = useGalleryPlayerStore((s) => s.markPlaybackStarted)
  const setFloatingPlayerCollapsed = useGalleryPlayerStore((s) => s.setFloatingPlayerCollapsed)
  const clearPlayback = useGalleryPlayerStore((s) => s.clearPlayback)
  const mediaVolume = useGalleryPlayerStore((s) => s.mediaVolume)
  const setMediaVolume = useGalleryPlayerStore((s) => s.setMediaVolume)

  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  /** Last-known playback while floating dock is visible — avoids resumeShouldPlay=false when unmount fires pause. */
  const playbackSnapshotRef = useRef({ time: 0, playing: false })

  const showDock =
    Boolean(mediaPath && mediaKind && currentView !== 'gallery' && playbackStarted) &&
    typeof window !== 'undefined' &&
    window.electronAPI

  const src = showDock && mediaPath ? window.electronAPI!.getAppMediaUrl(mediaPath) : ''

  useEffect(() => {
    if (!showDock || mediaKind !== 'video') {
      return
    }
    const v = videoRef.current
    if (!v) {
      return
    }
    const apply = () => {
      const { resumeSeconds: t, resumeShouldPlay: play, mediaVolume: mv } = useGalleryPlayerStore.getState()
      v.volume = mv
      if (Number.isFinite(v.duration) && t > 0.05 && t < v.duration) {
        v.currentTime = t
      } else if (!Number.isFinite(v.duration) && t > 0.05) {
        v.currentTime = t
      }
      if (play) {
        void v.play().catch(() => {})
      }
    }
    if (v.readyState >= 1) {
      apply()
    } else {
      v.addEventListener('loadedmetadata', apply, { once: true })
    }
  }, [showDock, mediaKind, src])

  useEffect(() => {
    if (!showDock || mediaKind !== 'audio') {
      return
    }
    const a = audioRef.current
    if (!a) {
      return
    }
    const apply = () => {
      const { resumeSeconds: t, resumeShouldPlay: play, mediaVolume: mv } = useGalleryPlayerStore.getState()
      a.volume = mv
      if (Number.isFinite(a.duration) && t > 0.05 && t < a.duration) {
        a.currentTime = t
      } else if (!Number.isFinite(a.duration) && t > 0.05) {
        a.currentTime = t
      }
      if (play) {
        void a.play().catch(() => {})
      }
    }
    if (a.readyState >= 1) {
      apply()
    } else {
      a.addEventListener('loadedmetadata', apply, { once: true })
    }
  }, [showDock, mediaKind, src])

  useLayoutEffect(() => {
    if (!showDock) {
      return
    }
    return () => {
      const s = playbackSnapshotRef.current
      useGalleryPlayerStore.getState().setPlaybackProgress(s.time, s.playing)
    }
  }, [showDock])

  useEffect(() => {
    if (!showDock) {
      return
    }
    if (mediaKind === 'video') {
      const v = videoRef.current
      if (v) {
        v.volume = mediaVolume
      }
      return
    }
    if (mediaKind === 'audio') {
      const a = audioRef.current
      if (a) {
        a.volume = mediaVolume
      }
    }
  }, [showDock, mediaKind, mediaVolume, src])

  const syncVideo = () => {
    const v = videoRef.current
    if (!v) {
      return
    }
    playbackSnapshotRef.current = { time: v.currentTime, playing: !v.paused && !v.ended }
    setPlaybackProgress(playbackSnapshotRef.current.time, playbackSnapshotRef.current.playing)
  }

  const syncAudio = () => {
    const a = audioRef.current
    if (!a) {
      return
    }
    playbackSnapshotRef.current = { time: a.currentTime, playing: !a.paused && !a.ended }
    setPlaybackProgress(playbackSnapshotRef.current.time, playbackSnapshotRef.current.playing)
  }

  if (!showDock || !mediaKind) {
    return null
  }

  const shell = hiddenPlaybackShellClass(collapsed)

  return (
    <div
      className={`fixed bottom-14 right-5 z-[90] flex flex-col overflow-hidden rounded-xl border border-glass-border bg-space-900 shadow-2xl ${
        collapsed ? 'w-auto max-w-[min(22rem,calc(100vw-2.5rem))]' : 'w-[min(22rem,calc(100vw-2.5rem))]'
      }`}
    >
      {collapsed ? (
        <div className="flex items-center gap-1 border-b border-glass-border px-2 py-1.5">
          <button
            type="button"
            onClick={() => setFloatingPlayerCollapsed(false)}
            className="rounded-lg p-1.5 text-space-400 transition-colors hover:bg-white/10 hover:text-white"
            title="Expand player"
          >
            <ChevronUp className="h-4 w-4" />
          </button>
          <span className="truncate pr-1 text-[11px] font-medium uppercase tracking-wide text-space-500">
            Playing
          </span>
          <button
            type="button"
            onClick={() => clearPlayback()}
            className="ml-auto rounded-lg p-1.5 text-space-400 transition-colors hover:bg-white/10 hover:text-white"
            title="Stop and dismiss player"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between border-b border-glass-border px-2 py-1.5">
          <span className="truncate pl-2 text-[11px] font-medium uppercase tracking-wide text-space-500">
            Now playing
          </span>
          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={() => setFloatingPlayerCollapsed(true)}
              className="rounded-lg p-1.5 text-space-400 transition-colors hover:bg-white/10 hover:text-white"
              title="Collapse player (playback continues)"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => clearPlayback()}
              className="rounded-lg p-1.5 text-space-400 transition-colors hover:bg-white/10 hover:text-white"
              title="Stop and dismiss player"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      <div className={shell}>
        {mediaKind === 'video' ? (
          <video
            ref={videoRef}
            className={`bg-black ${collapsed ? 'h-[120px] w-[160px]' : 'aspect-video w-full'}`}
            controls
            playsInline
            preload="metadata"
            src={src}
            onTimeUpdate={syncVideo}
            onVolumeChange={(e) => setMediaVolume(e.currentTarget.volume)}
            onPlay={() => {
              markPlaybackStarted()
              syncVideo()
            }}
            onEnded={() => {
              const v = videoRef.current
              setPlaybackProgress(v?.duration ?? 0, false)
            }}
          />
        ) : (
          <div className={collapsed ? 'flex flex-col gap-0 p-0' : 'flex flex-col gap-3 p-3'}>
            <div
              className={
                collapsed ? 'h-0 overflow-hidden opacity-0' : 'aspect-video w-full overflow-hidden rounded-lg bg-space-800'
              }
            >
              <GalleryThumb sources={thumbnailSources} className="h-full w-full object-cover" />
            </div>
            <audio
              ref={audioRef}
              className={collapsed ? 'h-[40px] w-[280px]' : 'w-full'}
              controls
              preload="metadata"
              src={src}
              onTimeUpdate={syncAudio}
              onVolumeChange={(e) => setMediaVolume(e.currentTarget.volume)}
              onPlay={() => {
                markPlaybackStarted()
                syncAudio()
              }}
              onEnded={() => {
                const a = audioRef.current
                setPlaybackProgress(a?.duration ?? 0, false)
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
