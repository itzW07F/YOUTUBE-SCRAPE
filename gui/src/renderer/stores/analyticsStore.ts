import { create } from 'zustand'
import type { AnalyticsSnapshot, OllamaReportPayload } from '../types/analyticsShared'

export type AnalyticsFolderSelectMode = 'user-change' | 'auto'

interface AnalyticsStoreState {
  selectedOutputDir: string
  snapshot: AnalyticsSnapshot | null
  llmReport: OllamaReportPayload | null
  llmError: string | null
  loadError: string | null
  isFetchingSnapshot: boolean
  setSelectedOutputDir: (dir: string, mode?: AnalyticsFolderSelectMode) => void
  setSnapshot: (snapshot: AnalyticsSnapshot | null) => void
  setLlmReport: (report: OllamaReportPayload | null) => void
  setLlmError: (message: string | null) => void
  setLoadError: (message: string | null) => void
  setIsFetchingSnapshot: (busy: boolean) => void
}

export const useAnalyticsStore = create<AnalyticsStoreState>((set) => ({
  selectedOutputDir: '',
  snapshot: null,
  llmReport: null,
  llmError: null,
  loadError: null,
  isFetchingSnapshot: false,

  setSelectedOutputDir: (dir, mode = 'auto') =>
    set(() =>
      mode === 'user-change'
        ? {
            selectedOutputDir: dir,
            snapshot: null,
            llmReport: null,
            llmError: null,
            loadError: null,
            isFetchingSnapshot: false,
          }
        : { selectedOutputDir: dir }
    ),

  setSnapshot: (snapshot) => set({ snapshot }),
  setLlmReport: (llmReport) => set({ llmReport }),
  setLlmError: (llmError) => set({ llmError }),
  setLoadError: (loadError) => set({ loadError }),
  setIsFetchingSnapshot: (isFetchingSnapshot) => set({ isFetchingSnapshot }),
}))
