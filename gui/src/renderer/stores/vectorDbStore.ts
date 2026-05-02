import { create } from 'zustand'
import type {
  RagStatusPayload,
  RagBuildResponse,
  RagGlobalStatusPayload,
} from '../types/analyticsShared'
import { joinServerUrl } from '../utils/joinServerUrl'

export type VectorDbViewMode = 'individual' | 'global'

export type RagBuildPhase = 'idle' | 'checking' | 'building' | 'completed' | 'failed'

interface VectorDbStoreState {
  // Individual view state
  selectedOutputDir: string
  ragStatus: RagStatusPayload | null
  isLoadingStatus: boolean
  statusError: string | null

  // Build state
  ragBuildPhase: RagBuildPhase
  ragBuildJobId: string | null
  ragBuildProgress: number
  ragBuildError: string | null
  lastBuildResult: { success: boolean; chunkCount: number } | null

  // Global view state
  viewMode: VectorDbViewMode
  globalStatus: RagGlobalStatusPayload | null
  isLoadingGlobal: boolean
  globalError: string | null

  // Actions
  setSelectedOutputDir: (dir: string) => void
  setRagStatus: (status: RagStatusPayload | null) => void
  setIsLoadingStatus: (loading: boolean) => void
  setStatusError: (error: string | null) => void

  setRagBuildPhase: (phase: RagBuildPhase) => void
  setRagBuildJobId: (jobId: string | null) => void
  setRagBuildProgress: (progress: number) => void
  setRagBuildError: (error: string | null) => void
  setLastBuildResult: (result: { success: boolean; chunkCount: number } | null) => void
  resetBuildState: () => void

  setViewMode: (mode: VectorDbViewMode) => void
  setGlobalStatus: (status: RagGlobalStatusPayload | null) => void
  setIsLoadingGlobal: (loading: boolean) => void
  setGlobalError: (error: string | null) => void
}

export const useVectorDbStore = create<VectorDbStoreState>((set) => ({
  // Individual view state
  selectedOutputDir: '',
  ragStatus: null,
  isLoadingStatus: false,
  statusError: null,

  // Build state
  ragBuildPhase: 'idle',
  ragBuildJobId: null,
  ragBuildProgress: 0,
  ragBuildError: null,
  lastBuildResult: null,

  // Global view state
  viewMode: 'individual',
  globalStatus: null,
  isLoadingGlobal: false,
  globalError: null,

  // Individual view actions
  setSelectedOutputDir: (dir) =>
    set({
      selectedOutputDir: dir,
      ragStatus: null,
      statusError: null,
      lastBuildResult: null,
    }),

  setRagStatus: (status) => set({ ragStatus: status }),
  setIsLoadingStatus: (loading) => set({ isLoadingStatus: loading }),
  setStatusError: (error) => set({ statusError: error }),

  // Build actions
  setRagBuildPhase: (phase) => set({ ragBuildPhase: phase }),
  setRagBuildJobId: (jobId) => set({ ragBuildJobId: jobId }),
  setRagBuildProgress: (progress) => set({ ragBuildProgress: progress }),
  setRagBuildError: (error) => set({ ragBuildError: error }),
  setLastBuildResult: (result) => set({ lastBuildResult: result }),

  resetBuildState: () =>
    set({
      ragBuildPhase: 'idle',
      ragBuildJobId: null,
      ragBuildProgress: 0,
      ragBuildError: null,
    }),

  // Global view actions
  setViewMode: (mode) => set({ viewMode: mode }),
  setGlobalStatus: (status) => set({ globalStatus: status }),
  setIsLoadingGlobal: (loading) => set({ isLoadingGlobal: loading }),
  setGlobalError: (error) => set({ globalError: error }),
}))

// Async helper to fetch RAG status
export async function fetchRagStatus(
  serverUrl: string,
  outputDir: string
): Promise<RagStatusPayload | null> {
  const res = await fetch(`${serverUrl}/analytics/rag-status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ output_dir: outputDir }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<RagStatusPayload>
}

// Async helper to start RAG build
export async function startRagBuild(
  serverUrl: string,
  outputDir: string,
  forceRefresh = false
): Promise<RagBuildResponse> {
  const res = await fetch(`${serverUrl}/analytics/rag-build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      output_dir: outputDir,
      force_refresh: forceRefresh,
    }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<RagBuildResponse>
}

// Async helper to fetch global status
export async function fetchGlobalRagStatus(
  serverUrl: string
): Promise<RagGlobalStatusPayload | null> {
  const res = await fetch(`${serverUrl}/analytics/rag-global-status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<RagGlobalStatusPayload>
}

/** GET /jobs/{job_id} for terminal build state when WebSocket messages are dropped. */
export async function fetchJobStatus(
  serverUrl: string,
  jobId: string
): Promise<Record<string, unknown> | null> {
  const res = await fetch(joinServerUrl(serverUrl, `/jobs/${jobId}`))
  if (res.status === 404) return null
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Record<string, unknown>>
}
