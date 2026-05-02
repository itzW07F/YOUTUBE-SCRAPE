/** electron-store keys + defaults for optional YouTube Data API v3 (must match spawn env in `python-bridge.ts`). */

export const YOUTUBE_DATA_API_STORE_DEFAULTS: {
  youtubeDataApiEnabled: boolean
  youtubeDataApiKey: string
} = {
  youtubeDataApiEnabled: false,
  youtubeDataApiKey: '',
}

/** Curated official Google documentation (live pages). */
export const YOUTUBE_DATA_API_DOC_LINKS: { label: string; url: string }[] = [
  { label: 'YouTube Data API overview', url: 'https://developers.google.com/youtube/v3' },
  { label: 'Getting started', url: 'https://developers.google.com/youtube/v3/getting-started' },
  { label: 'Request authorization (API keys)', url: 'https://developers.google.com/youtube/v3/guides/auth/legacy' },
  { label: 'Quota and cost', url: 'https://developers.google.com/youtube/v3/determine_quota_cost' },
  { label: 'API reference', url: 'https://developers.google.com/youtube/v3/docs' },
]
