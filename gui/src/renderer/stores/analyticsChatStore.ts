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

export type AnalyticsChatThreadState = {
  messages: AnalyticsChatApiMessage[]
  draft: string
  busy: boolean
  err: string | null
  lastWarnings: string[]
  diag: AnalyticsChatDiag | null
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
