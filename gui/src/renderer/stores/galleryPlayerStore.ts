import { create } from 'zustand'

export type GalleryMediaKind = 'video' | 'audio'

const DEFAULT_MEDIA_VOLUME = 0.65

function clampVolume(v: number): number {
  if (!Number.isFinite(v)) {
    return DEFAULT_MEDIA_VOLUME
  }
  return Math.min(1, Math.max(0, v))
}

interface GalleryPlayerState {
  mediaPath: string | null
  mediaKind: GalleryMediaKind | null
  thumbnailSources: string[]
  resumeSeconds: number
  resumeShouldPlay: boolean
  /** True after user starts playback (play event) for this media path; floating dock only shows when true. */
  playbackStarted: boolean
  /** Mini-mode: hide video/audio chrome but keep elements mounted so playback continues. */
  floatingPlayerCollapsed: boolean
  /** 0–1; shared between gallery and floating player so volume survives tab switches / remounts. */
  mediaVolume: number
  setActiveMedia: (path: string | null, kind: GalleryMediaKind | null, thumbs: string[]) => void
  setPlaybackProgress: (seconds: number, shouldPlay: boolean) => void
  setMediaVolume: (volume: number) => void
  markPlaybackStarted: () => void
  setFloatingPlayerCollapsed: (collapsed: boolean) => void
  clearPlayback: () => void
}

export const useGalleryPlayerStore = create<GalleryPlayerState>((set) => ({
  mediaPath: null,
  mediaKind: null,
  thumbnailSources: [],
  resumeSeconds: 0,
  resumeShouldPlay: false,
  playbackStarted: false,
  floatingPlayerCollapsed: false,
  mediaVolume: DEFAULT_MEDIA_VOLUME,

  setActiveMedia: (path, kind, thumbs) =>
    set((s) => {
      const pathChanged = path !== s.mediaPath
      return {
        mediaPath: path,
        mediaKind: kind,
        thumbnailSources: thumbs,
        resumeSeconds: pathChanged ? 0 : s.resumeSeconds,
        resumeShouldPlay: pathChanged ? false : s.resumeShouldPlay,
        playbackStarted: pathChanged ? false : s.playbackStarted,
        floatingPlayerCollapsed: pathChanged ? false : s.floatingPlayerCollapsed,
      }
    }),

  setPlaybackProgress: (seconds, shouldPlay) =>
    set({ resumeSeconds: seconds, resumeShouldPlay: shouldPlay }),

  setMediaVolume: (volume) => set({ mediaVolume: clampVolume(volume) }),

  markPlaybackStarted: () => set({ playbackStarted: true }),

  setFloatingPlayerCollapsed: (collapsed) => set({ floatingPlayerCollapsed: collapsed }),

  clearPlayback: () =>
    set((s) => ({
      mediaPath: null,
      mediaKind: null,
      thumbnailSources: [],
      resumeSeconds: 0,
      resumeShouldPlay: false,
      playbackStarted: false,
      floatingPlayerCollapsed: false,
      mediaVolume: s.mediaVolume,
    })),
}))
