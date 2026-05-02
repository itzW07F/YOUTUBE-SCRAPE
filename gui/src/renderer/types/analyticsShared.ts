/** Shared API payload types for Analytics (API + Zustand session). */

export interface MetadataHistoryPoint {
  captured_at: string
  video_id?: string | null
  view_count?: number | null
  like_count?: number | null
  dislike_count?: number | null
  comment_count?: number | null
}

export interface VideoMetricsSummary {
  video_id?: string | null
  title?: string | null
  channel_title?: string | null
  description?: string | null
  published_at?: string | null
  view_count?: number | null
  like_count?: number | null
  dislike_count?: number | null
  comment_count?: number | null
  duration_seconds?: number | null
}

export interface CommentVolumeBucket {
  bucket_start: string
  count: number
}

export interface LikeCountBucket {
  label: string
  count: number
}

export interface AuthorAggregate {
  author: string
  comment_count: number
  total_likes?: number | null
}

export interface KeywordTerm {
  term: string
  count: number
}

export interface CommentStats {
  total_flat: number
  top_level_count?: number | null
  reply_count?: number | null
  with_published_at: number
  volume_by_day: CommentVolumeBucket[]
  like_buckets: LikeCountBucket[]
  top_authors: AuthorAggregate[]
}

export interface AnalyticsSnapshot {
  schema_version: string
  output_dir: string
  video_metrics?: VideoMetricsSummary | null
  metadata_history: MetadataHistoryPoint[]
  metadata_history_points: number
  comments_file_present: boolean
  comment_stats?: CommentStats | null
  keywords: KeywordTerm[]
  notes: string[]
}

export interface OllamaMacroBrief {
  themes: string[]
  sentiment_overview: string
  suggestions_and_requests: string
  complaints_and_criticism: string
  agreements_and_disagreements: string
  notable_quotes: string[]
  caveats: string[]
}

export interface OllamaReportPayload {
  schema_version: string
  output_dir: string
  model: string
  generated_at: string
  from_cache: boolean
  comment_digest_meta: Record<string, unknown>
  brief: OllamaMacroBrief
}
