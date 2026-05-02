import { create } from 'zustand'
import type { AnalyticsChatApiMessage } from '../types/analyticsShared'
import { normalizeAnalyticsOutputDirKey } from '../utils/analyticsPathUtils'

export type AnalyticsChatDiag = {
  providerModelLine: string
  latencyMs: number
  scrapeBundleChars: number
  estScrapeTok: number
  estPromptTok: number
  promptTokens: number | null
  completionTokens: number | null
  totalTokens: number | null
  ragMode: 'legacy' | 'hybrid' | 'fallback_meta' | null
  ragChunks: number | null
  ragIndexBuildMs: number | null
  ragEmbedMs: number | null
}

/** Running totals for all successful chat completions in this thread (per scrape folder). */
export type AnalyticsChatSessionMetrics = {
  requestCount: number
  totalLatencyMs: number
  totalRagIndexBuildMs: number
  totalRagEmbedMs: number
  totalScrapeBundleChars: number
  totalEstScrapeTok: number
  totalEstPromptTok: number
  sumPromptTokens: number
  sumCompletionTokens: number
  sumTotalTokens: number
  promptTokenReports: number
  completionTokenReports: number
  totalTokenReports: number
}

export function emptySessionMetrics(): AnalyticsChatSessionMetrics {
  return {
    requestCount: 0,
    totalLatencyMs: 0,
    totalRagIndexBuildMs: 0,
    totalRagEmbedMs: 0,
    totalScrapeBundleChars: 0,
    totalEstScrapeTok: 0,
    totalEstPromptTok: 0,
    sumPromptTokens: 0,
    sumCompletionTokens: 0,
    sumTotalTokens: 0,
    promptTokenReports: 0,
    completionTokenReports: 0,
    totalTokenReports: 0,
  }
}

export function appendDiagToSessionMetrics(
  prev: AnalyticsChatSessionMetrics,
  d: AnalyticsChatDiag
): AnalyticsChatSessionMetrics {
  return {
    requestCount: prev.requestCount + 1,
    totalLatencyMs: prev.totalLatencyMs + d.latencyMs,
    totalRagIndexBuildMs: prev.totalRagIndexBuildMs + (d.ragIndexBuildMs ?? 0),
    totalRagEmbedMs: prev.totalRagEmbedMs + (d.ragEmbedMs ?? 0),
    totalScrapeBundleChars: prev.totalScrapeBundleChars + d.scrapeBundleChars,
    totalEstScrapeTok: prev.totalEstScrapeTok + d.estScrapeTok,
    totalEstPromptTok: prev.totalEstPromptTok + d.estPromptTok,
    sumPromptTokens: prev.sumPromptTokens + (d.promptTokens ?? 0),
    sumCompletionTokens: prev.sumCompletionTokens + (d.completionTokens ?? 0),
    sumTotalTokens: prev.sumTotalTokens + (d.totalTokens ?? 0),
    promptTokenReports: prev.promptTokenReports + (d.promptTokens != null ? 1 : 0),
    completionTokenReports: prev.completionTokenReports + (d.completionTokens != null ? 1 : 0),
    totalTokenReports: prev.totalTokenReports + (d.totalTokens != null ? 1 : 0),
  }
}

/** Maps session aggregates into the same shape as a single-reply diag for the metrics grid. */
export function sessionMetricsAsDisplayDiag(sp: AnalyticsChatSessionMetrics): AnalyticsChatDiag {
  const n = sp.requestCount
  return {
    providerModelLine: `Session · ${n} request${n === 1 ? '' : 's'}`,
    latencyMs: sp.totalLatencyMs,
    scrapeBundleChars: sp.totalScrapeBundleChars,
    estScrapeTok: sp.totalEstScrapeTok,
    estPromptTok: sp.totalEstPromptTok,
    promptTokens: sp.promptTokenReports > 0 ? sp.sumPromptTokens : null,
    completionTokens: sp.completionTokenReports > 0 ? sp.sumCompletionTokens : null,
    totalTokens: sp.totalTokenReports > 0 ? sp.sumTotalTokens : null,
    ragMode: null,
    ragChunks: null,
    ragIndexBuildMs: sp.totalRagIndexBuildMs > 0 ? sp.totalRagIndexBuildMs : null,
    ragEmbedMs: sp.totalRagEmbedMs > 0 ? sp.totalRagEmbedMs : null,
  }
}

export type AnalyticsChatPerfViewMode = 'last' | 'session'

export type AnalyticsChatThreadState = {
  messages: AnalyticsChatApiMessage[]
  draft: string
  busy: boolean
  err: string | null
  lastWarnings: string[]
  diag: AnalyticsChatDiag | null
  sessionPerf: AnalyticsChatSessionMetrics
  perfViewMode: AnalyticsChatPerfViewMode
  retryCount: number
  lastFailedMessages: AnalyticsChatApiMessage[] | null
}

export function emptyAnalyticsChatThreadState(): AnalyticsChatThreadState {
  return {
    messages: [],
    draft: '',
    busy: false,
    err: null,
    lastWarnings: [],
    diag: null,
    sessionPerf: emptySessionMetrics(),
    perfViewMode: 'last',
    retryCount: 0,
    lastFailedMessages: null,
  }
}

type AnalyticsChatStoreState = {
  threads: Record<string, AnalyticsChatThreadState>
  updateThread: (outputDirRaw: string, fn: (prev: AnalyticsChatThreadState) => AnalyticsChatThreadState) => void
  mergeThread: (outputDirRaw: string, patch: Partial<AnalyticsChatThreadState>) => void
  resetThread: (outputDirRaw: string) => void
}

export const useAnalyticsChatStore = create<AnalyticsChatStoreState>((set) => ({
  threads: {},
  updateThread: (outputDirRaw, fn) =>
    set((state) => {
      const folderKey = normalizeAnalyticsOutputDirKey(outputDirRaw).trim()
      if (!folderKey) {
        return state
      }
      const prev = state.threads[folderKey] ?? emptyAnalyticsChatThreadState()
      return { threads: { ...state.threads, [folderKey]: fn(prev) } }
    }),
  mergeThread: (outputDirRaw, patch) =>
    set((state) => {
      const folderKey = normalizeAnalyticsOutputDirKey(outputDirRaw).trim()
      if (!folderKey) {
        return state
      }
      const prev = state.threads[folderKey] ?? emptyAnalyticsChatThreadState()
      return { threads: { ...state.threads, [folderKey]: { ...prev, ...patch } } }
    }),
  resetThread: (outputDirRaw) =>
    set((state) => {
      const folderKey = normalizeAnalyticsOutputDirKey(outputDirRaw).trim()
      if (!folderKey) {
        return state
      }
      return { threads: { ...state.threads, [folderKey]: emptyAnalyticsChatThreadState() } }
    }),
}))
