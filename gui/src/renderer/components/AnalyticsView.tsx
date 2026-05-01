import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { BarChart3, Loader2, RefreshCw, Sparkles, LineChart, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'
import { useScrapeStore } from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'
import { useVideoResults } from '../hooks/useVideoResults'
import { openapiHasPostPath } from '../utils/analyticsApiProbe'
import { joinServerUrl } from '../utils/joinServerUrl'
import { readGuiAnalyticsLlmOverlay } from '../utils/guiAnalyticsLlmOverlay'
import { extractFastApiErrorDetail } from '../utils/fastApiErrorDetail'

async function augmentAnalyticsHttpError(serverUrl: string, res: Response, bodyText: string, routePath: string): Promise<string> {
  let msg = bodyText.trim() || `HTTP ${res.status}`
  if (res.status !== 404) {
    return msg
  }
  const probe = await openapiHasPostPath(serverUrl, routePath)
  if (probe === false) {
    msg += `\n\nThis API does not expose POST ${routePath}. The running Python backend is probably outdated. Use Debug → Restart Server (or rebuild the bundled API), then try again.`
  } else if (probe === null) {
    msg +=
      '\n\nCould not read /openapi.json to verify routes. Restart the Python API from Debug, or confirm nothing else is listening on the reported URL/port.'
  } else {
    msg +=
      '\n\n404 while OpenAPI lists this route — verify the server URL/port in Debug matches the API you intend (only one process should serve this app).'
  }
  return msg
}

interface MetadataHistoryPoint {
  captured_at: string
  video_id?: string | null
  view_count?: number | null
  like_count?: number | null
  dislike_count?: number | null
  comment_count?: number | null
}

interface VideoMetricsSummary {
  video_id?: string | null
  title?: string | null
  channel_title?: string | null
  published_at?: string | null
  view_count?: number | null
  like_count?: number | null
  dislike_count?: number | null
  comment_count?: number | null
  duration_seconds?: number | null
}

interface CommentVolumeBucket {
  bucket_start: string
  count: number
}

interface LikeCountBucket {
  label: string
  count: number
}

interface AuthorAggregate {
  author: string
  comment_count: number
  total_likes?: number | null
}

interface KeywordTerm {
  term: string
  count: number
}

interface CommentStats {
  total_flat: number
  top_level_count?: number | null
  reply_count?: number | null
  with_published_at: number
  volume_by_day: CommentVolumeBucket[]
  like_buckets: LikeCountBucket[]
  top_authors: AuthorAggregate[]
}

interface AnalyticsSnapshot {
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

interface OllamaMacroBrief {
  themes: string[]
  sentiment_overview: string
  suggestions_and_requests: string
  complaints_and_criticism: string
  agreements_and_disagreements: string
  notable_quotes: string[]
  caveats: string[]
}

interface OllamaReportPayload {
  schema_version: string
  output_dir: string
  model: string
  generated_at: string
  from_cache: boolean
  comment_digest_meta: Record<string, unknown>
  brief: OllamaMacroBrief
}

interface AnalyticsViewProps {
  onNavigateToGallery: () => void
}

function Sparkline({
  values,
  label,
  tone,
}: {
  values: Array<number | null | undefined>
  label: string
  tone: string
}): React.ReactElement | null {
  const nums = values.map((v) => (typeof v === 'number' && Number.isFinite(v) ? v : null))
  if (nums.every((v) => v === null)) {
    return (
      <div className="rounded-lg border border-white/10 bg-white/5 p-3">
        <p className="text-xs text-space-400">{label}</p>
        <p className="mt-2 text-sm text-space-500">No numeric series</p>
      </div>
    )
  }
  const resolved = nums.map((v) => (v === null ? 0 : v))
  const max = Math.max(...resolved, 1)
  const min = Math.min(...resolved, 0)
  const range = Math.max(max - min, 1)
  const w = 240
  const h = 56
  const step = nums.length > 1 ? w / (nums.length - 1) : w
  const points = nums.map((v, i) => {
    const val = v === null ? min : v
    const x = i * step
    const y = h - ((val - min) / range) * (h - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3">
      <p className="text-xs text-space-400">{label}</p>
      <svg width={w} height={h} className={`mt-2 overflow-visible ${tone}`}>
        <polyline
          fill="none"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          stroke="currentColor"
          points={points.join(' ')}
        />
      </svg>
      <p className="mt-1 font-mono text-[11px] text-space-500">
        first → last: {nums[0] ?? '—'} → {nums[nums.length - 1] ?? '—'}
      </p>
    </div>
  )
}

function HorizontalBars({
  buckets,
  title,
}: {
  buckets: Array<{ label: string; count: number }>
  title: string
}): React.ReactElement {
  const max = Math.max(...buckets.map((b) => b.count), 1)
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-4">
      <h4 className="text-sm font-semibold text-white">{title}</h4>
      <div className="mt-3 space-y-2">
        {buckets.map((b) => (
          <div key={b.label}>
            <div className="flex justify-between text-xs text-space-400">
              <span>{b.label}</span>
              <span>{b.count}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-space-800">
              <div
                className="h-full rounded-full bg-gradient-to-r from-neon-blue to-neon-purple"
                style={{ width: `${(b.count / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const AnalyticsView: React.FC<AnalyticsViewProps> = ({ onNavigateToGallery }) => {
  const jobs = useScrapeStore((s) => s.jobs)
  const galleryDiskRevisionBump = useScrapeStore((s) => s.galleryDiskRevisionBump)
  const results = useVideoResults(jobs, galleryDiskRevisionBump)
  const serverUrl = useAppStore((s) => s.serverUrl)
  const isServerRunning = useAppStore((s) => s.isServerRunning)

  const [selectedDir, setSelectedDir] = useState<string>('')
  const [snapshot, setSnapshot] = useState<AnalyticsSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [llmLoading, setLlmLoading] = useState(false)
  const [llmReport, setLlmReport] = useState<OllamaReportPayload | null>(null)
  const [llmError, setLlmError] = useState<string | null>(null)

  const sortedResults = useMemo(
    () => [...results].sort((a, b) => a.title.localeCompare(b.title)),
    [results]
  )

  useEffect(() => {
    if (!selectedDir && sortedResults.length > 0) {
      setSelectedDir(sortedResults[0].outputDir)
    }
  }, [selectedDir, sortedResults])

  const fetchSnapshot = useCallback(async () => {
    if (!serverUrl || !selectedDir) {
      toast.error('Pick a folder and ensure the API server is running.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(joinServerUrl(serverUrl, '/analytics/snapshot'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ output_dir: selectedDir }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(await augmentAnalyticsHttpError(serverUrl, res, text, '/analytics/snapshot'))
      }
      const data = (await res.json()) as AnalyticsSnapshot
      setSnapshot(data)
      toast.success('Analytics loaded')
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      toast.error('Could not load analytics')
    } finally {
      setLoading(false)
    }
  }, [serverUrl, selectedDir])

  const fetchLlm = useCallback(
    async (forceRefresh: boolean) => {
      if (!serverUrl || !selectedDir) {
        toast.error('Pick a folder and ensure the API server is running.')
        return
      }
      setLlmLoading(true)
      setLlmError(null)
      try {
        const guiOverlay = await readGuiAnalyticsLlmOverlay()
        const res = await fetch(joinServerUrl(serverUrl, '/analytics/ollama-report'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            output_dir: selectedDir,
            force_refresh: forceRefresh,
            gui_llm_overlay: guiOverlay ?? {},
          }),
        })
        if (!res.ok) {
          const text = await res.text()
          const extracted = extractFastApiErrorDetail(text)
          const hint = await augmentAnalyticsHttpError(serverUrl, res, text, '/analytics/ollama-report')
          throw new Error(extracted ?? hint)
        }
        const data = (await res.json()) as OllamaReportPayload
        setLlmReport(data)
        toast.success(data.from_cache ? 'Loaded cached AI brief' : 'Generated AI brief')
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        setLlmError(msg)
        toast.error('AI brief failed — check LLM Settings (remote URL, model) and API error detail below.')
      } finally {
        setLlmLoading(false)
      }
    },
    [serverUrl, selectedDir]
  )

  const hist = snapshot?.metadata_history ?? []
  const views = hist.map((h) => h.view_count)
  const likes = hist.map((h) => h.like_count)
  const dislikes = hist.map((h) => h.dislike_count)
  const pubComments = hist.map((h) => h.comment_count)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-display font-bold text-white">
            <BarChart3 className="h-7 w-7 text-neon-purple" />
            Analytics
          </h2>
          <p className="text-space-400">
            Deterministic stats from scrape files; optional LLM synthesis (configure in Settings — remote Ollama is sent on each request, no API restart needed).
          </p>
        </div>
        {!isServerRunning ? (
          <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            API offline — start the backend to load analytics.
          </div>
        ) : null}
      </div>

      <div className="glass-card p-5 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[240px] flex-1">
            <label className="block text-xs text-space-400 mb-1">Scrape folder</label>
            <select
              value={selectedDir}
              onChange={(e) => {
                setSelectedDir(e.target.value)
                setSnapshot(null)
                setLlmReport(null)
              }}
              className="futuristic-input w-full py-2"
            >
              {sortedResults.length === 0 ? (
                <option value="">No completed scrapes found</option>
              ) : (
                sortedResults.map((r) => (
                  <option key={r.id} value={r.outputDir}>
                    {r.title} ({r.videoId})
                  </option>
                ))
              )}
            </select>
          </div>
          <button
            type="button"
            onClick={() => void fetchSnapshot()}
            disabled={loading || !serverUrl || !selectedDir}
            className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Load data
          </button>
        </div>

        {snapshot?.metadata_history_points !== undefined && snapshot.metadata_history_points < 2 ? (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-neon-blue/30 bg-neon-blue/10 px-4 py-3 text-sm text-space-200">
            <LineChart className="h-5 w-5 shrink-0 text-neon-blue" />
            <span>
              Trend charts need at least two metadata snapshots. Use{' '}
              <button
                type="button"
                className="text-neon-cyan underline hover:text-white"
                onClick={onNavigateToGallery}
              >
                Video Gallery
              </button>{' '}
              metadata refresh to append <code className="text-neon-purple">metadata_history.jsonl</code>.
            </span>
          </div>
        ) : null}

        {error ? (
          <pre className="whitespace-pre-wrap rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
            {error}
          </pre>
        ) : null}
      </div>

      {snapshot ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-6"
        >
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="glass-card p-5 space-y-3">
              <h3 className="text-lg font-semibold text-white">Video snapshot</h3>
              {snapshot.video_metrics ? (
                <ul className="space-y-1 text-sm text-space-300">
                  <li>
                    <span className="text-space-500">Title:</span> {snapshot.video_metrics.title ?? '—'}
                  </li>
                  <li>
                    <span className="text-space-500">Channel:</span>{' '}
                    {snapshot.video_metrics.channel_title ?? '—'}
                  </li>
                  <li>
                    <span className="text-space-500">Views:</span>{' '}
                    {snapshot.video_metrics.view_count?.toLocaleString() ?? '—'}
                  </li>
                  <li>
                    <span className="text-space-500">Likes / Dislikes:</span>{' '}
                    {snapshot.video_metrics.like_count?.toLocaleString() ?? '—'} /{' '}
                    {snapshot.video_metrics.dislike_count?.toLocaleString() ?? '—'}
                  </li>
                  <li>
                    <span className="text-space-500">Public comment total:</span>{' '}
                    {snapshot.video_metrics.comment_count?.toLocaleString() ?? '—'}
                  </li>
                </ul>
              ) : (
                <p className="text-space-500 text-sm">No video.json metadata.</p>
              )}
            </div>

            <div className="glass-card p-5">
              <h3 className="text-lg font-semibold text-white mb-3">Performance over time</h3>
              {hist.length === 0 ? (
                <p className="text-sm text-space-500">No metadata history file.</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Sparkline values={views} label="Views" tone="text-neon-blue" />
                  <Sparkline values={likes} label="Likes" tone="text-neon-green" />
                  <Sparkline values={dislikes} label="Dislikes" tone="text-amber-400" />
                  <Sparkline values={pubComments} label="Public comment total" tone="text-neon-purple" />
                </div>
              )}
              <p className="mt-3 text-xs text-space-500">
                Points: {hist.length} (from metadata_history.jsonl). Capture times align with gallery refresh runs.
              </p>
            </div>
          </div>

          {snapshot.notes.length > 0 ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-space-400">
              {snapshot.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}

          {snapshot.comment_stats ? (
            <div className="grid gap-4 lg:grid-cols-3">
              <HorizontalBars buckets={snapshot.comment_stats.like_buckets} title="Comment likes (bucket)" />
              <div className="rounded-lg border border-white/10 bg-white/5 p-4 lg:col-span-2">
                <h4 className="text-sm font-semibold text-white">Comments per day (UTC)</h4>
                {snapshot.comment_stats.volume_by_day.length === 0 ? (
                  <p className="mt-2 text-sm text-space-500">No dated comments.</p>
                ) : (
                  <div className="mt-3 max-h-56 space-y-2 overflow-y-auto pr-1">
                    {(() => {
                      const max = Math.max(...snapshot.comment_stats.volume_by_day.map((b) => b.count), 1)
                      return snapshot.comment_stats.volume_by_day.map((b) => (
                        <div key={b.bucket_start}>
                          <div className="flex justify-between text-xs text-space-400">
                            <span>{b.bucket_start}</span>
                            <span>{b.count}</span>
                          </div>
                          <div className="mt-1 h-2 overflow-hidden rounded-full bg-space-800">
                            <div
                              className="h-full rounded-full bg-neon-cyan/80"
                              style={{ width: `${(b.count / max) * 100}%` }}
                            />
                          </div>
                        </div>
                      ))
                    })()}
                  </div>
                )}
                <p className="mt-2 text-xs text-space-500">
                  Flat comments: {snapshot.comment_stats.total_flat}, with timestamp:{' '}
                  {snapshot.comment_stats.with_published_at}, replies:{' '}
                  {snapshot.comment_stats.reply_count ?? '—'}
                </p>
              </div>
            </div>
          ) : null}

          {snapshot.comment_stats && snapshot.comment_stats.top_authors.length > 0 ? (
            <div className="glass-card overflow-hidden p-0">
              <div className="border-b border-white/10 px-5 py-3">
                <h3 className="text-lg font-semibold text-white">Top authors (volume)</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-white/5 text-space-400">
                    <tr>
                      <th className="px-5 py-2 font-medium">Author</th>
                      <th className="px-5 py-2 font-medium">Comments</th>
                      <th className="px-5 py-2 font-medium">Σ likes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.comment_stats.top_authors.map((a) => (
                      <tr key={a.author} className="border-t border-white/5">
                        <td className="px-5 py-2 text-space-200">{a.author}</td>
                        <td className="px-5 py-2 text-space-300">{a.comment_count}</td>
                        <td className="px-5 py-2 text-space-300">{a.total_likes ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {snapshot.keywords.length > 0 ? (
            <div className="glass-card overflow-hidden p-0">
              <div className="border-b border-white/10 px-5 py-3">
                <h3 className="text-lg font-semibold text-white">Top tokens (English heuristic)</h3>
                <p className="text-xs text-space-500">
                  Naïve word frequencies — supplement with the AI brief for themes.
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-white/5 text-space-400">
                    <tr>
                      <th className="px-5 py-2 font-medium">Term</th>
                      <th className="px-5 py-2 font-medium">Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.keywords.map((k) => (
                      <tr key={k.term} className="border-t border-white/5">
                        <td className="px-5 py-2 font-mono text-neon-cyan">{k.term}</td>
                        <td className="px-5 py-2 text-space-300">{k.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <div className="glass-card border border-neon-purple/25 p-5 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
                  <Sparkles className="h-5 w-5 text-neon-purple" />
                  AI macro brief (Ollama)
                </h3>
                <p className="mt-1 text-sm text-space-400">
                  Audience reactions inferred from <strong className="text-space-300">your scraped comments only</strong>{' '}
                  (themes, tone, splits — language patterns, not clinical diagnoses). Requires local Ollama (
                  <code className="text-space-300">YOUTUBE_SCRAPE_OLLAMA_*</code>). Use{' '}
                  <strong className="text-space-300">Force refresh</strong> after updates so prompts apply.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={llmLoading || !serverUrl || !selectedDir}
                  onClick={() => void fetchLlm(false)}
                  className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
                >
                  {llmLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Generate / load cached
                </button>
                <button
                  type="button"
                  disabled={llmLoading || !serverUrl || !selectedDir}
                  onClick={() => void fetchLlm(true)}
                  className="futuristic-btn flex items-center gap-2"
                >
                  Force refresh
                </button>
              </div>
            </div>

            {llmError ? (
              <pre className="whitespace-pre-wrap rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
                {llmError}
              </pre>
            ) : null}

            {llmReport ? (
              <div className="space-y-4 rounded-lg border border-white/10 bg-space-900/40 p-4">
                <p className="text-xs text-space-500">
                  Model {llmReport.model} · {llmReport.generated_at}{' '}
                  {llmReport.from_cache ? '(cache)' : '(fresh)'}
                </p>
                <div>
                  <h4 className="text-sm font-semibold text-neon-blue">Themes</h4>
                  <ul className="mt-1 list-disc pl-5 text-sm text-space-300">
                    {llmReport.brief.themes.map((t, i) => (
                      <li key={`${i}-${t}`}>{t}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-neon-blue">Sentiment (overview)</h4>
                  <p className="mt-1 text-sm text-space-300">{llmReport.brief.sentiment_overview}</p>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <h4 className="text-sm font-semibold text-neon-green">Suggestions / requests</h4>
                    <p className="mt-1 text-sm text-space-300">{llmReport.brief.suggestions_and_requests}</p>
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-amber-400">Complaints / criticism</h4>
                    <p className="mt-1 text-sm text-space-300">{llmReport.brief.complaints_and_criticism}</p>
                  </div>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-neon-purple">Agreements / disagreements</h4>
                  <p className="mt-1 text-sm text-space-300">{llmReport.brief.agreements_and_disagreements}</p>
                </div>
                {llmReport.brief.notable_quotes.length > 0 ? (
                  <div>
                    <h4 className="text-sm font-semibold text-space-200">Notable excerpts</h4>
                    <ul className="mt-1 list-disc pl-5 text-sm italic text-space-400">
                      {llmReport.brief.notable_quotes.map((q, i) => (
                        <li key={`${i}-${q.slice(0, 24)}`}>{q}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {llmReport.brief.caveats.length > 0 ? (
                  <div>
                    <h4 className="text-sm font-semibold text-rose-300">Caveats</h4>
                    <ul className="mt-1 list-disc pl-5 text-sm text-space-400">
                      {llmReport.brief.caveats.map((c, i) => (
                        <li key={`${i}-${c.slice(0, 24)}`}>{c}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </motion.div>
      ) : null}
    </div>
  )
}

export default AnalyticsView
