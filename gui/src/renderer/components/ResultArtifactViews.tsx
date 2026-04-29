import React, { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'

type ArtifactKind = 'video' | 'comments' | 'transcript' | 'thumbnails' | 'media' | 'summary'

interface OutputArtifactRead {
  kind: ArtifactKind
  fileName: string | null
  contentType: 'json' | 'text' | 'images' | 'media'
  content: string | null
  truncated: boolean
}

interface StructuredArtifactPreviewProps {
  artifact: OutputArtifactRead
  /** Pretty-printed JSON string when structured parsing fails */
  fallbackContent: string
}

function parseJson(content: string): unknown | null {
  try {
    return JSON.parse(content) as unknown
  } catch {
    return null
  }
}

function record(root: unknown): Record<string, unknown> | null {
  return root !== null && typeof root === 'object' && !Array.isArray(root)
    ? (root as Record<string, unknown>)
    : null
}

function pickData(envelope: Record<string, unknown>): Record<string, unknown> {
  const inner = envelope.data
  if (inner !== null && typeof inner === 'object' && !Array.isArray(inner)) {
    return inner as Record<string, unknown>
  }
  return envelope
}

/** Human-readable panels for video.json / comments.json / summary.json / thumbnails.json — not raw JSON dumps */
export function StructuredArtifactPreview({
  artifact,
  fallbackContent,
}: StructuredArtifactPreviewProps): React.ReactElement {
  const parsed = artifact.content ? parseJson(artifact.content) : null

  if (parsed === null) {
    return (
      <div className="min-w-0 w-full space-y-3">
        <JsonFallbackPre truncated={artifact.truncated}>
          {fallbackContent || 'No content'}
        </JsonFallbackPre>
      </div>
    )
  }

  let inner: React.ReactElement
  switch (artifact.kind) {
    case 'video':
      inner = (
        <VideoArtifactView
          root={parsed}
          truncated={artifact.truncated}
          fallbackContent={fallbackContent}
        />
      )
      break
    case 'comments':
      inner = (
        <CommentsArtifactView
          root={parsed}
          truncated={artifact.truncated}
          fallbackContent={fallbackContent}
        />
      )
      break
    case 'summary':
      inner = (
        <SummaryArtifactView
          root={parsed}
          truncated={artifact.truncated}
          fallbackContent={fallbackContent}
        />
      )
      break
    case 'thumbnails':
      inner = (
        <ThumbnailsArtifactView
          root={parsed}
          truncated={artifact.truncated}
          fallbackContent={fallbackContent}
        />
      )
      break
    default:
      inner = (
        <JsonFallbackPre truncated={artifact.truncated}>
          {fallbackContent || 'No content'}
        </JsonFallbackPre>
      )
  }

  return <div className="min-w-0 w-full space-y-3">{inner}</div>
}

function JsonFallbackPre({
  children,
  truncated,
}: {
  children: string
  truncated: boolean
}): React.ReactElement {
  return (
    <div className="min-w-0 w-full">
      <pre className="max-h-[32rem] min-h-0 w-full min-w-0 overflow-auto rounded-lg bg-black/40 p-4 text-xs leading-relaxed text-space-200">
        <code className="block w-full min-w-0 whitespace-pre font-mono text-left">{children}</code>
      </pre>
      {truncated ? (
        <p className="mt-2 text-xs text-amber-200">
          This file is large, so only the first portion is shown.
        </p>
      ) : null}
    </div>
  )
}

function RawJsonDisclosure({
  label,
  fallbackContent,
  truncated,
}: {
  label: string
  fallbackContent: string
  truncated: boolean
}): React.ReactElement {
  return (
    <details className="rounded-lg border border-glass-border bg-black/20">
      <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-space-400 hover:text-space-200">
        {label}
      </summary>
      <div className="border-t border-glass-border px-3 pb-3 pt-1">
        <JsonFallbackPre truncated={truncated}>{fallbackContent}</JsonFallbackPre>
      </div>
    </details>
  )
}

function VideoArtifactView({
  root,
  truncated,
  fallbackContent,
}: {
  root: unknown
  truncated: boolean
  fallbackContent: string
}): React.ReactElement {
  const env = record(root)
  const data = env ? pickData(env) : {}
  const meta = record(data.metadata) ?? {}

  const title = pickStr(meta.title)
  const channel = pickStr(meta.channel_title)
  const videoId = pickStr(meta.video_id)
  const views = meta.view_count
  const likes = meta.like_count
  const dislikes = meta.dislike_count
  const duration = meta.duration_seconds
  const description = pickStr(meta.description)
  const published = formatPublished(meta.published_at, pickStr(meta.published_text))
  const dislikeSource =
    typeof meta.dislike_source === 'string' ? meta.dislike_source : undefined

  const captions = Array.isArray(data.caption_tracks) ? data.caption_tracks : []
  const streams = Array.isArray(data.stream_formats_preview) ? data.stream_formats_preview : []
  const streamTotal =
    typeof data.stream_formats_total === 'number' ? data.stream_formats_total : streams.length

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-glass-border bg-white/[0.04] p-4 md:grid-cols-2">
        <div className="md:col-span-2">
          <h4 className="text-lg font-semibold leading-snug text-white">
            {title || 'Video metadata'}
          </h4>
          <p className="mt-1 text-sm text-neon-blue/90">{channel || '—'}</p>
        </div>
        <Stat label="Video ID" value={videoId || '—'} mono />
        <Stat label="Duration" value={formatDuration(duration)} />
        <Stat label="Views" value={formatNum(views)} />
        <Stat label="Likes" value={formatNum(likes)} />
        <div>
          <Stat label="Dislikes" value={formatNum(dislikes)} />
          {dislikeSource === 'return_youtube_dislike' && (
            <p className="mt-0.5 text-[10px] text-space-500" title="Estimate from Return YouTube Dislike project">
              RYD community estimate
            </p>
          )}
        </div>
        <Stat label="Published" value={published} />
      </div>

      {description ? (
        <section className="rounded-lg border border-glass-border bg-black/25 p-4">
          <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-space-500">
            Description
          </h5>
          <p className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-sm leading-relaxed text-space-200">
            {description}
          </p>
        </section>
      ) : null}

      <section className="rounded-lg border border-glass-border bg-black/20">
        <h5 className="border-b border-glass-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-space-500">
          Caption tracks ({captions.length})
        </h5>
        {captions.length === 0 ? (
          <p className="p-4 text-sm text-space-400">None listed.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[28rem] text-left text-xs">
              <thead className="bg-space-900/50 text-space-400">
                <tr>
                  <th className="px-3 py-2 font-medium">Language</th>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Kind</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-glass-border text-space-200">
                {captions.map((row, i) => {
                  const r = record(row) ?? {}
                  return (
                    <tr key={i}>
                      <td className="px-3 py-2 font-mono">{pickStr(r.language_code) || '—'}</td>
                      <td className="px-3 py-2">{pickStr(r.name) || '—'}</td>
                      <td className="px-3 py-2">{pickStr(r.kind) || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <details className="rounded-lg border border-glass-border bg-black/20">
        <summary className="cursor-pointer select-none border-b border-glass-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-space-500 list-none [&::-webkit-details-marker]:hidden">
          Stream formats (preview {streams.length} of {streamTotal})
        </summary>
        <div>
          {streams.length === 0 ? (
            <p className="p-4 text-sm text-space-400">None listed.</p>
          ) : (
            <div className="max-h-72 overflow-auto">
              <table className="w-full min-w-[36rem] text-left text-xs">
                <thead className="sticky top-0 z-[1] bg-space-900/95 text-space-400 backdrop-blur">
                  <tr>
                    <th className="px-3 py-2 font-medium">Itag</th>
                    <th className="px-3 py-2 font-medium">Quality</th>
                    <th className="px-3 py-2 font-medium">MIME</th>
                    <th className="px-3 py-2 font-medium">A/V</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-glass-border text-space-200">
                  {streams.map((row, i) => {
                    const r = record(row) ?? {}
                    const itag = r.itag
                    const av =
                      r.has_video === true && r.has_audio === true
                        ? 'A+V'
                        : r.has_video === true
                          ? 'V'
                          : r.has_audio === true
                            ? 'A'
                            : '—'
                    return (
                      <tr key={i}>
                        <td className="px-3 py-2 font-mono">
                          {typeof itag === 'number' ? itag : '—'}
                        </td>
                        <td className="px-3 py-2">{pickStr(r.quality_label) || '—'}</td>
                        <td className="max-w-[14rem] truncate px-3 py-2 font-mono text-[11px]">
                          {pickStr(r.mime_type) || '—'}
                        </td>
                        <td className="px-3 py-2 text-neon-blue/90">{av}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </details>

      <RawJsonDisclosure
        label="Raw JSON (video.json)"
        fallbackContent={fallbackContent}
        truncated={truncated}
      />
    </div>
  )
}

const COMMENTS_PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const

function CommentsArtifactView({
  root,
  truncated,
  fallbackContent,
}: {
  root: unknown
  truncated: boolean
  fallbackContent: string
}): React.ReactElement {
  const env = record(root)
  const data = env ? pickData(env) : {}
  const videoId = pickStr(data.video_id)
  const total = typeof data.total_count === 'number' ? data.total_count : null
  const topLevel = typeof data.top_level_count === 'number' ? data.top_level_count : null
  const threads = Array.isArray(data.comments) ? data.comments : []

  const [pageIndex, setPageIndex] = useState(0)
  const [pageSize, setPageSize] = useState<number>(COMMENTS_PAGE_SIZE_OPTIONS[1])

  const listFingerprint = useMemo(() => {
    if (threads.length === 0) {
      return `empty|${videoId}`
    }
    const first = record(threads[0])
    const last = record(threads[threads.length - 1])
    const a = first && typeof first.comment_id === 'string' ? first.comment_id : ''
    const b = last && typeof last.comment_id === 'string' ? last.comment_id : ''
    return `${videoId}|${threads.length}|${a}|${b}`
  }, [threads, videoId])

  useEffect(() => {
    setPageIndex(0)
  }, [listFingerprint])

  const totalPages = Math.max(1, Math.ceil(threads.length / pageSize) || 1)

  useEffect(() => {
    setPageIndex((p) => Math.min(p, totalPages - 1))
  }, [totalPages])

  const safePage = Math.min(pageIndex, totalPages - 1)
  const start = safePage * pageSize
  const end = Math.min(start + pageSize, threads.length)
  const pageThreads = threads.slice(start, start + pageSize)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
        {videoId ? (
          <span className="text-space-400">
            Video{' '}
            <code className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-xs text-neon-blue">
              {videoId}
            </code>
          </span>
        ) : null}
        {total != null ? <span className="text-space-400">Comments scraped: {total}</span> : null}
        {topLevel != null ? (
          <span className="text-space-400">Top-level threads: {topLevel}</span>
        ) : null}
      </div>

      {threads.length > 0 ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <p className="text-xs text-space-500">
            Showing{' '}
            <span className="font-medium text-space-300">
              {threads.length === 0 ? 0 : start + 1}–{end}
            </span>{' '}
            of{' '}
            <span className="font-medium text-space-300">{threads.length}</span> thread
            {threads.length === 1 ? '' : 's'}
            <span
              className="ml-1.5 text-space-600"
              title="Each thread is one top-level comment plus its replies, loaded as one unit."
            >
              (replies stay with parent)
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-space-400">
              <span className="shrink-0">Per page</span>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setPageIndex(0)
                }}
                className="rounded-lg border border-glass-border bg-black/40 py-1.5 pl-2 pr-8 text-sm text-space-200 focus:border-neon-blue/50 focus:outline-none focus:ring-1 focus:ring-neon-blue/30"
                title="Number of top-level comment threads per page"
              >
                {COMMENTS_PAGE_SIZE_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPageIndex((p) => Math.max(0, p - 1))}
                disabled={safePage <= 0}
                className="rounded-lg border border-glass-border p-2 text-space-300 transition-colors hover:bg-white/[0.06] hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
                title="Previous page"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="min-w-[5.5rem] px-2 text-center text-xs text-space-400">
                {safePage + 1} / {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPageIndex((p) => Math.min(totalPages - 1, p + 1))}
                disabled={safePage >= totalPages - 1}
                className="rounded-lg border border-glass-border p-2 text-space-300 transition-colors hover:bg-white/[0.06] hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
                title="Next page"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="max-h-[min(32rem,70vh)] space-y-3 overflow-y-auto pr-1">
        {threads.length === 0 ? (
          <p className="text-sm text-space-400">No comments in this file.</p>
        ) : (
          pageThreads.map((thread, i) => (
            <CommentThreadBlock key={commentThreadKey(thread, start + i)} thread={thread} />
          ))
        )}
      </div>

      <RawJsonDisclosure
        label="Raw JSON (comments.json)"
        fallbackContent={fallbackContent}
        truncated={truncated}
      />
    </div>
  )
}

function commentThreadKey(thread: unknown, index: number): string {
  const r = record(thread)
  if (r && typeof r.comment_id === 'string') {
    return r.comment_id
  }
  return `thread-${index}`
}

function CommentThreadBlock({ thread }: { thread: unknown }): React.ReactElement | null {
  const r = record(thread)
  if (!r) {
    return null
  }

  if (typeof r._note === 'string' && Array.isArray(r.orphan_replies)) {
    return (
      <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-4">
        <p className="text-xs font-medium text-amber-200">{r._note}</p>
        <div className="mt-2 space-y-2 border-l-2 border-amber-500/40 pl-3">
          {r.orphan_replies.map((reply, i) => (
            <CommentBubble key={replyRecordKey(reply, `orphan-${i}`)} comment={reply} nested />
          ))}
        </div>
      </div>
    )
  }

  const replies = Array.isArray(r.replies) ? r.replies : []

  return (
    <div className="rounded-lg border border-glass-border bg-white/[0.04] p-4 shadow-sm">
      <CommentBubble comment={thread} />
      {replies.length > 0 ? (
        <div className="mt-3 space-y-2 border-l-2 border-neon-blue/35 pl-4 ml-1">
          {replies.map((reply, i) => (
            <CommentBubble key={replyRecordKey(reply, `reply-${i}`)} comment={reply} nested />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function replyRecordKey(reply: unknown, fallback: string): string {
  const r = record(reply)
  if (r && typeof r.comment_id === 'string') {
    return r.comment_id
  }
  return fallback
}

function CommentBubble({
  comment,
  nested,
}: {
  comment: unknown
  nested?: boolean
}): React.ReactElement | null {
  const r = record(comment)
  if (!r) {
    return null
  }
  const text = pickStr(r.text) || ''
  const author = pickStr(r.author) || 'Unknown'
  const when = pickStr(r.published_text)
  const likes = r.like_count

  return (
    <div className={nested ? 'rounded-md bg-black/20 py-2 pl-2 pr-2' : ''}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-white">{author}</span>
        {when ? <span className="text-xs text-space-500">{when}</span> : null}
        {likes != null ? <span className="text-xs text-space-400">♥ {String(likes)}</span> : null}
      </div>
      <p
        className={`mt-1.5 whitespace-pre-wrap break-words text-sm leading-relaxed text-space-200 ${nested ? '' : ''}`}
      >
        {text || '(empty)'}
      </p>
    </div>
  )
}

function SummaryArtifactView({
  root,
  truncated,
  fallbackContent,
}: {
  root: unknown
  truncated: boolean
  fallbackContent: string
}): React.ReactElement {
  const doc = record(root)
  if (!doc) {
    return <JsonFallbackPre truncated={truncated}>{fallbackContent}</JsonFallbackPre>
  }

  const videoId = pickStr(doc.video_id)
  const outDir = pickStr(doc.output_directory)
  const ops = Array.isArray(doc.operations_run) ? doc.operations_run.map(String) : []
  const results = record(doc.results)

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-glass-border bg-white/[0.04] p-4">
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-space-500">Video ID</dt>
            <dd className="mt-0.5 font-mono text-space-200">{videoId || '—'}</dd>
          </div>
          <div className="md:col-span-2">
            <dt className="text-xs uppercase tracking-wide text-space-500">Output directory</dt>
            <dd className="mt-0.5 break-all font-mono text-xs text-space-300">{outDir || '—'}</dd>
          </div>
        </dl>
      </div>

      <section>
        <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-space-500">
          Operations
        </h5>
        <div className="flex flex-wrap gap-2">
          {ops.length === 0 ? (
            <span className="text-sm text-space-400">None listed.</span>
          ) : (
            ops.map(op => (
              <span
                key={op}
                className="rounded-full border border-neon-blue/30 bg-neon-blue/10 px-3 py-1 text-xs font-medium text-neon-blue"
              >
                {op}
              </span>
            ))
          )}
        </div>
      </section>

      {results ? (
        <section className="space-y-2">
          <h5 className="text-xs font-semibold uppercase tracking-wide text-space-500">
            Per-operation snapshot
          </h5>
          <div className="space-y-2">
            {Object.entries(results).map(([key, value]) => (
              <SummaryOperationAccordion key={key} opName={key} payload={value} />
            ))}
          </div>
        </section>
      ) : null}

      <RawJsonDisclosure
        label="Raw JSON (summary.json)"
        fallbackContent={fallbackContent}
        truncated={truncated}
      />
    </div>
  )
}

function SummaryOperationAccordion({
  opName,
  payload,
}: {
  opName: string
  payload: unknown
}): React.ReactElement {
  const [open, setOpen] = useState(false)
  const oneLine = summarizeOperationPayload(payload)

  return (
    <div className="rounded-lg border border-glass-border bg-black/25">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-white hover:bg-white/[0.04]"
        onClick={() => setOpen(o => !o)}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-neon-blue" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-space-500" />
        )}
        <span className="font-medium capitalize">{opName}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-space-400">{oneLine}</span>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="summary-operation-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <div className="border-t border-glass-border px-3 py-3">
              <pre className="max-h-60 overflow-auto rounded-md bg-black/40 p-3 text-[11px] leading-relaxed text-space-200">
                <code className="break-words whitespace-pre-wrap font-mono">
                  {safeJsonStringify(payload)}
                </code>
              </pre>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  )
}

function summarizeOperationPayload(payload: unknown): string {
  const env = record(payload)
  if (!env) {
    return ''
  }
  const kind = pickStr(env.kind)
  const data = record(env.data)
  if (!data) {
    return kind ? `kind: ${kind}` : ''
  }
  if (kind === 'video') {
    const meta = record(data.metadata)
    const title = meta ? pickStr(meta.title) : ''
    return title ? `Video · ${title.slice(0, 80)}${title.length > 80 ? '…' : ''}` : 'Video metadata'
  }
  if (kind === 'comments') {
    const n = typeof data.total_count === 'number' ? data.total_count : null
    return n != null ? `${n} comments` : 'Comments'
  }
  if (kind === 'transcript') {
    return 'Transcript'
  }
  if (kind === 'thumbnails') {
    const c = typeof data.count === 'number' ? data.count : null
    return c != null ? `${c} thumbnails saved` : 'Thumbnails'
  }
  if (kind === 'download') {
    return 'Download'
  }
  return kind ? `kind: ${kind}` : 'Result'
}

function ThumbnailsArtifactView({
  root,
  truncated,
  fallbackContent,
}: {
  root: unknown
  truncated: boolean
  fallbackContent: string
}): React.ReactElement {
  const env = record(root)
  const data = env ? pickData(env) : {}
  const title = pickStr(data.title)
  const vid = pickStr(data.video_id)
  const count = typeof data.count === 'number' ? data.count : null
  const saved = Array.isArray(data.saved) ? data.saved : []

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-glass-border bg-white/[0.04] p-4">
        <h4 className="text-base font-semibold text-white">{title || 'Thumbnails'}</h4>
        <p className="mt-1 text-sm text-space-400">
          {vid ? (
            <>
              Video{' '}
              <code className="rounded bg-white/10 px-1 font-mono text-xs text-neon-blue">
                {vid}
              </code>
            </>
          ) : null}
          {count != null ? <span className="ml-2">· {count} files</span> : null}
        </p>
      </div>

      {saved.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-glass-border bg-black/20">
          <table className="w-full min-w-[28rem] text-left text-xs">
            <thead className="bg-space-900/50 text-space-400">
              <tr>
                <th className="px-3 py-2 font-medium">Size</th>
                <th className="px-3 py-2 font-medium">Bytes</th>
                <th className="px-3 py-2 font-medium">URL</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-glass-border text-space-200">
              {saved.map((row, i) => {
                const r = record(row) ?? {}
                const w = r.width
                const h = r.height
                const bytes = r.bytes
                const url = pickStr(r.url)
                return (
                  <tr key={i}>
                    <td className="px-3 py-2 whitespace-nowrap font-mono">
                      {typeof w === 'number' && typeof h === 'number' ? `${w}×${h}` : '—'}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      {typeof bytes === 'number' ? bytes.toLocaleString() : '—'}
                    </td>
                    <td
                      className="max-w-[min(28rem,50vw)] truncate px-3 py-2 font-mono text-[11px] text-space-400"
                      title={url}
                    >
                      {url || '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-space-400">No saved thumbnail rows in JSON.</p>
      )}

      <RawJsonDisclosure
        label="Raw JSON (thumbnails metadata)"
        fallbackContent={fallbackContent}
        truncated={truncated}
      />
    </div>
  )
}

function Stat({
  label,
  value,
  mono,
}: {
  label: string
  value: string
  mono?: boolean
}): React.ReactElement {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-space-500">{label}</p>
      <p className={`mt-0.5 text-sm text-space-200 ${mono ? 'font-mono text-xs' : ''}`}>{value}</p>
    </div>
  )
}

function pickStr(v: unknown): string {
  if (v === null || v === undefined) {
    return ''
  }
  return String(v)
}

function formatNum(v: unknown): string {
  if (typeof v === 'number' && Number.isFinite(v)) {
    return v.toLocaleString()
  }
  return '—'
}

function formatPublished(iso: unknown, textFallback: string): string {
  if (typeof iso === 'string' && iso.length > 0) {
    const ms = Date.parse(iso)
    if (!Number.isNaN(ms)) {
      return new Date(ms).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    }
  }
  if (textFallback) {
    return textFallback
  }
  return '—'
}

function formatDuration(seconds: unknown): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) {
    return '—'
  }
  const s = Math.floor(seconds % 60)
  const m = Math.floor((seconds / 60) % 60)
  const h = Math.floor(seconds / 3600)
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }
  return `${m}:${String(s).padStart(2, '0')}`
}

function safeJsonStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
