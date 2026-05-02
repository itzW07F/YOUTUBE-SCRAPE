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

export interface MacroBriefTiming {
  total_ms: number
  rag_resolve_ms: number
  digest_build_ms: number
  ensure_ready_ms: number
  llm_main_ms: number
  llm_repair_ms: number
  llm_refill_ms: number
  llm_plain_ms: number
  llm_plain_repair_ms: number
}

export interface OllamaReportPayload {
  schema_version: string
  output_dir: string
  model: string
  generated_at: string
  from_cache: boolean
  comment_digest_meta: Record<string, unknown>
  brief: OllamaMacroBrief
  macro_brief_timing?: MacroBriefTiming | null
}

/** Client-visible chat turns mirrored in ``POST /analytics/chat`` ``messages``. */
export interface AnalyticsChatApiMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface AnalyticsChatResponsePayload {
  schema_version: '1'
  assistant: string
  warnings: string[]
  provider: string
  model: string
  llm_latency_ms: number
  scrape_bundle_chars: number
  estimated_scrape_bundle_tokens: number
  estimated_request_prompt_tokens: number
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  analytics_rag_mode?: 'legacy' | 'hybrid' | 'fallback_meta' | null
  analytics_rag_chunks_used?: number | null
  analytics_rag_index_build_ms?: number | null
  analytics_rag_embed_ms?: number | null
}

/** RAG vectorization status for a scrape output folder. */
export interface RagStatusPayload {
  schema_version: '1'
  output_dir: string
  is_vectorized: boolean
  chunk_count: number
  embed_model: string | null
  embed_dim: number | null
  last_updated: string | null
  eligible_sources: string[]
  missing_sources: string[]
  has_download_only: boolean
}

/** Response after triggering RAG build. */
export interface RagBuildResponse {
  schema_version: '1'
  job_id: string
  output_dir: string
  status: 'started' | 'failed'
  message: string
}

/** Vectorization status for one video in global view. */
export interface RagGlobalStatusItem {
  output_dir: string
  video_id: string | null
  title: string | null
  is_vectorized: boolean
  chunk_count: number
  embed_model: string | null
  last_updated: string | null
  has_scrape_data: boolean
}

/** Global view of vectorization status across all videos. */
export interface RagGlobalStatusPayload {
  schema_version: '1'
  videos: RagGlobalStatusItem[]
  total_count: number
  vectorized_count: number
  pending_count: number
  download_only_count: number
}
