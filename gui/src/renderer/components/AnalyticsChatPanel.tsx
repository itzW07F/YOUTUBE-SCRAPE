import React, { useCallback, useLayoutEffect, useMemo, useRef } from 'react'
import { Loader2, MessageSquare, RefreshCw, SendHorizontal, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import type { AnalyticsChatApiMessage, AnalyticsChatResponsePayload, AnalyticsSnapshot } from '../types/analyticsShared'
import { joinServerUrl } from '../utils/joinServerUrl'
import { readGuiAnalyticsLlmOverlay } from '../utils/guiAnalyticsLlmOverlay'
import { extractFastApiErrorDetail } from '../utils/fastApiErrorDetail'
import { openapiHasPostPath } from '../utils/analyticsApiProbe'
import { normalizeAnalyticsOutputDirKey } from '../utils/analyticsPathUtils'
import {
  appendDiagToSessionMetrics,
  emptyAnalyticsChatThreadState,
  emptySessionMetrics,
  sessionMetricsAsDisplayDiag,
  useAnalyticsChatStore,
  type AnalyticsChatDiag,
  type AnalyticsChatPerfViewMode,
} from '../stores/analyticsChatStore'

async function augmentAnalyticsChatError(serverUrl: string, res: Response, bodyText: string): Promise<string> {
  const routePath = '/analytics/chat'
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

/** Animated placeholder shown while the backend LLM request is in flight; replaced by the real assistant message on completion. */
function AssistantPendingBubble(): React.ReactElement {
  return (
    <div
      className="assistant-bubble-pending mr-6 rounded-lg border border-neon-purple/35 bg-gradient-to-br from-white/[0.07] to-space-900/50 px-3 py-2.5 text-sm shadow-[0_0_14px_rgba(168,85,247,0.12)]"
      aria-live="polite"
      aria-busy="true"
      aria-label="Assistant is generating a reply"
    >
      <p className="text-[10px] font-semibold uppercase tracking-wide text-neon-purple/85">Assistant</p>
      <div className="mt-2 flex items-center gap-3">
        <div className="flex items-center gap-1.5" role="presentation">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="inline-block h-2 w-2 rounded-full bg-neon-purple motion-safe:animate-bounce shadow-[0_0_8px_rgba(168,85,247,0.45)]"
              style={{
                animationDuration: '0.6s',
                animationDelay: `${i * 130}ms`,
              }}
            />
          ))}
        </div>
        <span className="text-xs text-space-400 italic">Thinking with your scrape context…</span>
      </div>
    </div>
  )
}

export const AnalyticsChatPanel: React.FC<{
  serverUrl: string
  selectedDir: string
  snapshot: AnalyticsSnapshot | null
  folderReady: boolean
  isServerRunning: boolean
}> = ({ serverUrl, selectedDir, snapshot, folderReady, isServerRunning }) => {
  const folderKey = useMemo(() => normalizeAnalyticsOutputDirKey(selectedDir.trim()).trim(), [selectedDir])

  const slice = useAnalyticsChatStore((s) => (folderKey.length > 0 ? s.threads[folderKey] : undefined))

  const mergeThread = useAnalyticsChatStore((s) => s.mergeThread)
  const updateThread = useAnalyticsChatStore((s) => s.updateThread)
  const resetThread = useAnalyticsChatStore((s) => s.resetThread)

  const messages = slice?.messages ?? []
  const draft = slice?.draft ?? ''
  const busy = slice?.busy ?? false
  const err = slice?.err ?? null
  const lastWarnings = slice?.lastWarnings ?? []
  const diag: AnalyticsChatDiag | null = slice?.diag ?? null
  const sessionPerf = slice?.sessionPerf ?? emptySessionMetrics()
  const perfViewMode: AnalyticsChatPerfViewMode = slice?.perfViewMode ?? 'last'
  const retryCount = slice?.retryCount ?? 0
  const lastFailedMessages = slice?.lastFailedMessages ?? null

  const chatScrollRef = useRef<HTMLDivElement>(null)
  /** Aligns the app main scroll region so the bottom of this chat card stays in view when the panel grows. */
  const chatPageAlignRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const el = chatScrollRef.current
    if (!el) {
      return
    }
    el.scrollTop = el.scrollHeight
  }, [messages, busy])

  useLayoutEffect(() => {
    const el = chatPageAlignRef.current
    if (!el) {
      return
    }
    const chatActive =
      busy ||
      messages.length > 0 ||
      diag != null ||
      Boolean(err) ||
      lastWarnings.length > 0
    if (!chatActive) {
      return
    }

    const main = el.closest('main')
    if (main instanceof HTMLElement) {
      const pad = 2
      const er = el.getBoundingClientRect()
      const mr = main.getBoundingClientRect()
      const bottomClipped = er.bottom > mr.bottom - pad
      const topClipped = er.top < mr.top + pad
      if (!bottomClipped && !topClipped) {
        return
      }
    }

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    el.scrollIntoView({ block: 'end', behavior: reduced ? 'auto' : 'smooth' })
  }, [busy, messages, diag, err, lastWarnings])

  const displayDiag: AnalyticsChatDiag | null = useMemo(() => {
    if (!diag) {
      return null
    }
    if (perfViewMode === 'session' && sessionPerf.requestCount > 0) {
      return sessionMetricsAsDisplayDiag(sessionPerf)
    }
    return diag
  }, [diag, perfViewMode, sessionPerf])

  const isSessionPerfView = Boolean(displayDiag && perfViewMode === 'session' && sessionPerf.requestCount > 0)
  const sessionTokenPartial =
    isSessionPerfView &&
    (sessionPerf.promptTokenReports < sessionPerf.requestCount ||
      sessionPerf.completionTokenReports < sessionPerf.requestCount ||
      sessionPerf.totalTokenReports < sessionPerf.requestCount)

  const setDraftLocal = useCallback(
    (nextDraft: string) => {
      if (!folderKey) {
        return
      }
      mergeThread(folderKey, { draft: nextDraft })
    },
    [folderKey, mergeThread]
  )

  const canSend = useMemo(() => {
    return (
      folderReady &&
      folderKey.length > 0 &&
      Boolean(serverUrl.trim()) &&
      Boolean(selectedDir.trim()) &&
      isServerRunning &&
      !busy &&
      draft.trim().length > 0
    )
  }, [folderReady, folderKey, serverUrl, selectedDir, isServerRunning, busy, draft])

  const canRetry = useMemo(() => {
    return (
      folderReady &&
      folderKey.length > 0 &&
      Boolean(serverUrl.trim()) &&
      Boolean(selectedDir.trim()) &&
      isServerRunning &&
      !busy &&
      lastFailedMessages != null &&
      err != null
    )
  }, [folderReady, folderKey, serverUrl, selectedDir, isServerRunning, busy, lastFailedMessages, err])

  const send = useCallback(
    async (messagesToSend?: AnalyticsChatApiMessage[], isRetry = false) => {
      const key = normalizeAnalyticsOutputDirKey(selectedDir).trim()
      if (!key || !folderReady || !serverUrl.trim() || !selectedDir.trim() || !isServerRunning) {
        return
      }

      const readThread = () =>
        useAnalyticsChatStore.getState().threads[key] ?? emptyAnalyticsChatThreadState()

      let outgoing: AnalyticsChatApiMessage[]
      const cur = readThread()

      if (messagesToSend) {
        outgoing = messagesToSend
      } else if (cur.draft.trim()) {
        outgoing = [...cur.messages, { role: 'user', content: cur.draft.trim() }]
      } else {
        return
      }

      if (!isRetry) {
        mergeThread(key, { messages: outgoing, draft: '', retryCount: 0 })
      }

      mergeThread(key, {
        busy: true,
        err: null,
        lastWarnings: [],
        lastFailedMessages: null,
      })

      let res: Response | undefined
      try {
        const guiOverlay = await readGuiAnalyticsLlmOverlay()
        res = await fetch(joinServerUrl(serverUrl, '/analytics/chat'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            output_dir: selectedDir,
            messages: outgoing,
            gui_llm_overlay: guiOverlay ?? {},
          }),
        })
        const text = await res.text()
        if (!res.ok) {
          const extracted = extractFastApiErrorDetail(text)
          const hint = await augmentAnalyticsChatError(serverUrl, res, text)
          throw new Error(extracted ?? hint)
        }
        let data: AnalyticsChatResponsePayload
        try {
          data = JSON.parse(text) as AnalyticsChatResponsePayload
        } catch {
          throw new Error('Invalid JSON response from /analytics/chat.')
        }
        const pt = typeof data.prompt_tokens === 'number' ? data.prompt_tokens : null
        const ct = typeof data.completion_tokens === 'number' ? data.completion_tokens : null
        const tt = typeof data.total_tokens === 'number' ? data.total_tokens : null

        const newDiag: AnalyticsChatDiag = {
          providerModelLine: `${data.provider} · ${data.model}`,
          latencyMs: data.llm_latency_ms,
          scrapeBundleChars: data.scrape_bundle_chars,
          estScrapeTok: data.estimated_scrape_bundle_tokens,
          estPromptTok: data.estimated_request_prompt_tokens,
          promptTokens: pt,
          completionTokens: ct,
          totalTokens: tt,
          ragMode: typeof data.analytics_rag_mode === 'string' ? data.analytics_rag_mode : null,
          ragChunks: typeof data.analytics_rag_chunks_used === 'number' ? data.analytics_rag_chunks_used : null,
          ragIndexBuildMs:
            typeof data.analytics_rag_index_build_ms === 'number' ? data.analytics_rag_index_build_ms : null,
          ragEmbedMs: typeof data.analytics_rag_embed_ms === 'number' ? data.analytics_rag_embed_ms : null,
        }

        updateThread(key, (prev) => ({
          ...prev,
          messages: [...outgoing, { role: 'assistant', content: data.assistant }],
          lastWarnings: data.warnings?.length ? [...data.warnings] : [],
          diag: newDiag,
          sessionPerf: appendDiagToSessionMetrics(prev.sessionPerf ?? emptySessionMetrics(), newDiag),
          retryCount: 0,
          lastFailedMessages: null,
        }))
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)

        mergeThread(key, {
          err: msg,
          lastFailedMessages: outgoing,
        })

        const priorRetryCount = readThread().retryCount
        const isTransientError =
          msg.toLowerCase().includes('unexpected eof') ||
          msg.toLowerCase().includes('failed to sample token') ||
          msg.toLowerCase().includes('out of memory') ||
          msg.toLowerCase().includes('context length exceeded') ||
          res?.status === 502 ||
          res?.status === 503 ||
          res?.status === 504

        if (!isRetry && priorRetryCount === 0 && isTransientError) {
          toast.success('LLM error detected — retrying once...', { duration: 3000 })
          mergeThread(key, { retryCount: 1 })
          await new Promise((resolve) => setTimeout(resolve, 2000))
          await send(outgoing, true)
          return
        }

        toast.error('Chat request failed — check LLM Settings and backend logs.')
      } finally {
        mergeThread(key, { busy: false })
      }
    },
    [folderReady, isServerRunning, mergeThread, selectedDir, serverUrl, updateThread]
  )

  const retry = useCallback(() => {
    if (!folderKey || !lastFailedMessages) {
      return
    }
    mergeThread(folderKey, { retryCount: retryCount + 1 })
    void send(lastFailedMessages, true)
  }, [folderKey, lastFailedMessages, mergeThread, retryCount, send])

  const clear = useCallback(() => {
    if (!folderKey) {
      return
    }
    resetThread(folderKey)
  }, [folderKey, resetThread])

  const gated =
    !isServerRunning || !snapshot || !folderReady || !selectedDir.trim() ? (
      <p className="text-sm text-amber-200/90">
        {!isServerRunning
          ? 'Start the Python API to use chat.'
          : !selectedDir.trim()
            ? 'Select a scrape folder and load data first.'
            : !snapshot
              ? 'Load analytics snapshot (Load data) before chatting.'
              : 'Snapshot folder does not match the selected scrape folder — reload data.'}
      </p>
    ) : null

  return (
    <div className="glass-card overflow-hidden border border-neon-purple/25">
      <div className="flex items-start gap-3 border-b border-white/10 px-5 py-3">
        <MessageSquare className="mt-0.5 h-5 w-5 shrink-0 text-neon-purple" />
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-semibold text-white">Ask the AI (scraped context)</h3>
          <p className="text-xs text-space-500">
            Each reply uses this scrape folder only. With <strong className="text-space-300">RAG</strong> enabled
            (Settings → Ollama), Ask the AI may use retrieved excerpts + a metadata header to save context;
            otherwise the server sends a full text bundle within size limits. Configure the provider in Settings.
          </p>
        </div>
        <button
          type="button"
          onClick={clear}
          disabled={busy || (messages.length === 0 && !draft.trim() && !err)}
          className="futuristic-btn flex shrink-0 items-center gap-1.5 text-sm"
          title="Clear conversation"
        >
          <Trash2 className="h-4 w-4" />
          Clear
        </button>
      </div>
      <div className="space-y-3 p-5">
        {gated}
        {displayDiag ? (
          <div className="rounded-xl border border-neon-purple/20 bg-gradient-to-br from-space-900/80 to-space-950/90 p-4 shadow-lg shadow-neon-purple/5">
            <div className="mb-4 flex flex-col gap-3 border-b border-white/10 pb-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-white flex items-center gap-2">
                  <span className="h-2 w-2 shrink-0 rounded-full bg-neon-green animate-pulse"></span>
                  Response Metrics
                </p>
                <p className="mt-0.5 text-xs text-space-400 font-mono break-all">{displayDiag.providerModelLine}</p>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                {diag && sessionPerf.requestCount > 0 ? (
                  <div
                    className="inline-flex rounded-lg border border-white/15 bg-space-950/60 p-0.5"
                    role="tablist"
                    aria-label="Performance scope"
                  >
                    <button
                      type="button"
                      role="tab"
                      aria-selected={perfViewMode === 'last'}
                      onClick={() => folderKey && mergeThread(folderKey, { perfViewMode: 'last' })}
                      className={`rounded-md px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide transition-colors ${
                        perfViewMode === 'last'
                          ? 'bg-neon-purple/25 text-white'
                          : 'text-space-400 hover:text-space-200'
                      }`}
                    >
                      This reply
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={perfViewMode === 'session'}
                      onClick={() => folderKey && mergeThread(folderKey, { perfViewMode: 'session' })}
                      className={`rounded-md px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide transition-colors ${
                        perfViewMode === 'session'
                          ? 'bg-neon-purple/25 text-white'
                          : 'text-space-400 hover:text-space-200'
                      }`}
                    >
                      Session ({sessionPerf.requestCount})
                    </button>
                  </div>
                ) : null}
                {isSessionPerfView ? (
                  <span className="inline-flex items-center rounded-full bg-neon-blue/15 px-2.5 py-1 text-xs font-medium text-neon-cyan border border-neon-blue/25">
                    Sum across chat
                  </span>
                ) : diag?.ragMode ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-neon-purple/15 px-2.5 py-1 text-xs font-medium text-neon-purple border border-neon-purple/30">
                    RAG {diag.ragMode}
                    {diag.ragChunks != null && (
                      <span className="text-space-400">· {diag.ragChunks} chunks</span>
                    )}
                  </span>
                ) : (
                  <span className="inline-flex items-center rounded-full bg-space-800/80 px-2.5 py-1 text-xs font-medium text-space-400 border border-space-700">
                    Full context
                  </span>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-space-950/50 border border-white/5 p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-neon-cyan mb-2">Performance</p>
                <div className="space-y-1.5">
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-space-400">
                      {isSessionPerfView ? 'LLM runtime (sum)' : 'LLM runtime'}
                    </span>
                    <span className="text-sm font-semibold text-white tabular-nums">
                      {displayDiag.latencyMs.toLocaleString()}
                      <span className="text-xs font-normal text-space-500 ml-0.5">ms</span>
                    </span>
                  </div>
                  {displayDiag.ragIndexBuildMs != null && displayDiag.ragIndexBuildMs > 0 && (
                    <div className="flex items-baseline justify-between">
                      <span className="text-xs text-space-400">
                        {isSessionPerfView ? 'Index build (sum)' : 'Index build'}
                      </span>
                      <span className="text-xs font-medium text-neon-purple tabular-nums">
                        +{displayDiag.ragIndexBuildMs.toLocaleString()}
                        <span className="text-space-500 ml-0.5">ms</span>
                      </span>
                    </div>
                  )}
                  {displayDiag.ragEmbedMs != null && displayDiag.ragEmbedMs > 0 && (
                    <div className="flex items-baseline justify-between">
                      <span className="text-xs text-space-400">
                        {isSessionPerfView ? 'Query embed (sum)' : 'Query embed'}
                      </span>
                      <span className="text-xs font-medium text-neon-purple tabular-nums">
                        +{displayDiag.ragEmbedMs.toLocaleString()}
                        <span className="text-space-500 ml-0.5">ms</span>
                      </span>
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-lg bg-space-950/50 border border-white/5 p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-neon-cyan mb-2">Context</p>
                <div className="space-y-1.5">
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-space-400">
                      {isSessionPerfView ? 'Bundle size (sum)' : 'Bundle size'}
                    </span>
                    <span className="text-sm font-semibold text-white tabular-nums">
                      {displayDiag.scrapeBundleChars.toLocaleString()}
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-space-400">
                      {isSessionPerfView ? 'Est. tokens (sum)' : 'Est. tokens'}
                    </span>
                    <span className="text-xs text-space-300 tabular-nums">
                      ~{displayDiag.estScrapeTok.toLocaleString()}
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-space-400">
                      {isSessionPerfView ? 'Prompt est. (sum)' : 'Prompt est.'}
                    </span>
                    <span className="text-xs text-space-300 tabular-nums">
                      ~{displayDiag.estPromptTok.toLocaleString()}
                    </span>
                  </div>
                </div>
              </div>

              <div className="col-span-2 rounded-lg bg-gradient-to-r from-neon-blue/5 to-transparent border border-neon-blue/10 p-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-neon-blue mb-2">
                  {isSessionPerfView ? 'Token usage (sum)' : 'Token Usage'}
                </p>
                <div className="grid grid-cols-3 gap-3">
                  <div className="text-center">
                    <p className="text-xs text-space-400 mb-0.5">Prompt</p>
                    <p className="text-lg font-bold text-white tabular-nums">
                      {displayDiag.promptTokens != null ? displayDiag.promptTokens.toLocaleString() : '—'}
                    </p>
                  </div>
                  <div className="text-center border-x border-white/5">
                    <p className="text-xs text-space-400 mb-0.5">Completion</p>
                    <p className="text-lg font-bold text-neon-green tabular-nums">
                      {displayDiag.completionTokens != null ? displayDiag.completionTokens.toLocaleString() : '—'}
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-space-400 mb-0.5">Total</p>
                    <p className="text-lg font-bold text-neon-cyan tabular-nums">
                      {displayDiag.totalTokens != null ? displayDiag.totalTokens.toLocaleString() : '—'}
                    </p>
                  </div>
                </div>
                {displayDiag.promptTokens == null &&
                  displayDiag.completionTokens == null &&
                  displayDiag.totalTokens == null && (
                    <p className="mt-2 text-[10px] text-center text-space-500 italic">
                      Provider did not return token counts
                    </p>
                  )}
                {sessionTokenPartial ? (
                  <p className="mt-2 text-[10px] text-center text-amber-200/80">
                    Some replies did not report usage; sums include reported values only.
                  </p>
                ) : null}
              </div>
            </div>

            <p className="mt-3 text-[10px] leading-relaxed text-space-500 text-center">
              Token estimates use chars÷4 heuristic. Provider counts may differ, especially for non-Latin scripts.
            </p>
          </div>
        ) : null}
        {lastWarnings.length > 0 ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
            <div className="flex items-start justify-between gap-3">
              <ul className="list-disc space-y-1 text-xs text-amber-100/90 pl-4">
                {lastWarnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
              <button
                type="button"
                onClick={() => folderKey && mergeThread(folderKey, { lastWarnings: [] })}
                className="shrink-0 rounded-md px-2 py-1 text-[10px] font-medium text-amber-200/80 hover:bg-amber-500/20 hover:text-amber-100 transition-colors"
                aria-label="Dismiss warnings"
              >
                Dismiss
              </button>
            </div>
          </div>
        ) : null}
        {err ? (
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3">
            <pre className="whitespace-pre-wrap text-sm text-rose-200">{err}</pre>
            {canRetry && (
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void retry()}
                  disabled={busy}
                  className="futuristic-btn futuristic-btn-primary flex items-center gap-1.5 text-sm"
                >
                  <RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />
                  {busy ? 'Retrying...' : retryCount > 0 ? `Retry (${retryCount})` : 'Retry'}
                </button>
                <span className="text-xs text-rose-300/70">
                  {retryCount > 0 ? 'Auto-retry attempted' : 'Click to retry the request'}
                </span>
              </div>
            )}
          </div>
        ) : null}
        <div
          ref={chatScrollRef}
          className="max-h-[22rem] space-y-3 overflow-y-auto rounded-lg border border-white/10 bg-space-950/40 p-3"
        >
          {messages.length === 0 && !busy ? (
            <p className="text-sm text-space-500">Ask a question about this video&apos;s scrape data.</p>
          ) : (
            <>
              {messages.map((m, i) => (
                <div
                  key={`${i}-${m.role}-${m.content.slice(0, 12)}`}
                  className={`rounded-lg px-3 py-2 text-sm ${
                    m.role === 'user'
                      ? 'ml-6 border border-neon-blue/25 bg-neon-blue/10 text-space-100'
                      : 'mr-6 border border-white/10 bg-white/5 text-space-200'
                  }`}
                >
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-space-500">
                    {m.role === 'user' ? 'You' : 'Assistant'}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap">{m.content}</p>
                </div>
              ))}
              {busy ? <AssistantPendingBubble /> : null}
            </>
          )}
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <textarea
            value={draft}
            onChange={(e) => setDraftLocal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (canSend) {
                  void send()
                }
              }
            }}
            disabled={!folderReady || !isServerRunning || busy}
            placeholder={
              folderReady && isServerRunning ? 'Message… (Enter to send, Shift+Enter newline)' : 'Unavailable'
            }
            rows={3}
            className="futuristic-input min-h-[5rem] flex-1 resize-y py-2 font-sans text-sm"
          />
          <button
            type="button"
            disabled={!canSend}
            onClick={() => void send()}
            className="futuristic-btn futuristic-btn-primary flex shrink-0 items-center justify-center gap-2 sm:min-w-[7rem]"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizontal className="h-4 w-4" />}
            Send
          </button>
        </div>
      </div>
      <div
        ref={chatPageAlignRef}
        className="h-px w-full scroll-mb-6 shrink-0 overflow-hidden pointer-events-none"
        aria-hidden="true"
      />
    </div>
  )
}
