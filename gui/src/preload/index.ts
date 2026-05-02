import { contextBridge, ipcRenderer } from 'electron'

// Define the API that will be exposed to the renderer process
const api = {
  // Python server lifecycle
  startPythonServer: (): Promise<{ success: boolean; error?: string }> =>
    ipcRenderer.invoke('python:start'),
  restartPythonServer: (): Promise<{ success: boolean; error?: string }> =>
    ipcRenderer.invoke('python:restart'),
  stopPythonServer: (): Promise<{ success: boolean; error?: string }> =>
    ipcRenderer.invoke('python:stop'),
  getServerStatus: (): Promise<{ running: boolean; port?: number; url?: string }> =>
    ipcRenderer.invoke('python:status'),
  onServerLog: (callback: (event: unknown, log: { level: string; message: string; timestamp: string }) => void) => {
    ipcRenderer.on('python:log', callback)
    return () => ipcRenderer.removeListener('python:log', callback)
  },

  // File system operations
  selectDirectory: (): Promise<{ canceled: boolean; filePaths: string[] }> =>
    ipcRenderer.invoke('dialog:selectDirectory'),
  selectFile: (filters?: { name: string; extensions: string[] }[]): Promise<{ canceled: boolean; filePaths: string[] }> =>
    ipcRenderer.invoke('dialog:selectFile', filters),
  openPath: (path: string): Promise<string | void> =>
    ipcRenderer.invoke('shell:openPath', path),
  openExternal: (url: string): Promise<{ ok: boolean; error?: string }> =>
    ipcRenderer.invoke('shell:openExternal', url),
  showItemInFolder: (path: string): Promise<void> =>
    ipcRenderer.invoke('shell:showItemInFolder', path),

  // App information
  getAppVersion: (): Promise<string> => ipcRenderer.invoke('app:version'),
  getAppLogDirectory: (): Promise<string> => ipcRenderer.invoke('app:logDirectory'),
  appendAppLog: (
    level: 'debug' | 'info' | 'warn' | 'error',
    scope: string,
    message: string,
    detail?: unknown
  ): Promise<void> => ipcRenderer.invoke('app:appendLog', { level, scope, message, detail }),
  getPlatform: (): Promise<string> =>
    ipcRenderer.invoke('app:platform'),
  getAppRuntime: (): Promise<{ arch: string; node: string; electron: string }> =>
    ipcRenderer.invoke('app:runtime'),
  getAppMediaUrl: (absolutePath: string): string => {
    const p = Buffer.from(absolutePath, 'utf8').toString('base64url')
    return `appmedia://local/?p=${encodeURIComponent(p)}`
  },
  readOutputVideoMeta: (outputDir: string) => ipcRenderer.invoke('output:readVideoMeta', outputDir),
  listOutputMediaFiles: (outputDir: string) => ipcRenderer.invoke('output:listMediaFiles', outputDir),
  readOutputArtifact: (
    outputDir: string,
    kind: 'video' | 'comments' | 'transcript' | 'thumbnails' | 'media' | 'summary'
  ) => ipcRenderer.invoke('output:readArtifact', outputDir, kind),
  discoverScrapeOutputs: (): Promise<
    Array<{
      outputDir: string
      videoId: string
      url: string
      completedAt: string
    }>
  > => ipcRenderer.invoke('output:discoverScrapes'),
  deleteOutputScrapeDir: (outputDir: string): Promise<{ ok: boolean; error?: string }> =>
    ipcRenderer.invoke('output:deleteScrapeDir', outputDir),

  analyticsNotesList: (
    outputDir: string
  ): Promise<
    | { ok: true; files: Array<{ id: string; displayName: string }> }
    | { ok: false; error: string }
  > => ipcRenderer.invoke('analyticsNotes:list', outputDir),
  analyticsNotesRead: (
    outputDir: string,
    fileId: string
  ): Promise<{ ok: true; content: string } | { ok: false; error: string }> =>
    ipcRenderer.invoke('analyticsNotes:read', outputDir, fileId),
  analyticsNotesWrite: (
    outputDir: string,
    fileId: string,
    content: string
  ): Promise<{ ok: true } | { ok: false; error: string }> =>
    ipcRenderer.invoke('analyticsNotes:write', outputDir, fileId, content),
  analyticsNotesCreate: (
    outputDir: string,
    displayName?: string
  ): Promise<
    | { ok: true; file: { id: string; displayName: string } }
    | { ok: false; error: string }
  > => ipcRenderer.invoke('analyticsNotes:create', outputDir, displayName),
  analyticsNotesDelete: (
    outputDir: string,
    fileId: string
  ): Promise<
    | { ok: true; files: Array<{ id: string; displayName: string }> }
    | { ok: false; error: string }
  > => ipcRenderer.invoke('analyticsNotes:delete', outputDir, fileId),
  analyticsNotesRename: (
    outputDir: string,
    fileId: string,
    displayName: string
  ): Promise<
    | { ok: true; file: { id: string; displayName: string } }
    | { ok: false; error: string }
  > => ipcRenderer.invoke('analyticsNotes:rename', outputDir, fileId, displayName),

  // Window controls
  minimizeWindow: (): Promise<void> =>
    ipcRenderer.invoke('window:minimize'),
  maximizeWindow: (): Promise<void> =>
    ipcRenderer.invoke('window:maximize'),
  closeWindow: (): Promise<void> =>
    ipcRenderer.invoke('window:close'),
  isWindowMaximized: (): Promise<boolean> =>
    ipcRenderer.invoke('window:isMaximized'),
  onWindowStateChange: (callback: (event: unknown, state: { isMaximized: boolean }) => void) => {
    ipcRenderer.on('window:state-changed', callback)
    return () => ipcRenderer.removeListener('window:state-changed', callback)
  },

  // Store operations for persistent settings
  storeGet: (key: string): Promise<unknown> =>
    ipcRenderer.invoke('store:get', key),
  storeSet: (key: string, value: unknown): Promise<void> =>
    ipcRenderer.invoke('store:set', key, value),
  storeDelete: (key: string): Promise<void> =>
    ipcRenderer.invoke('store:delete', key),

  dashboardTrackersGet: (): Promise<import('../shared/dashboardTrackers').DashboardTrackers> =>
    ipcRenderer.invoke('dashboardTrackers:get'),
  dashboardTrackersApplyIncrements: (
    increments: import('../shared/dashboardTrackers').DashboardTrackerIncrements
  ): Promise<import('../shared/dashboardTrackers').DashboardTrackers> =>
    ipcRenderer.invoke('dashboardTrackers:applyIncrements', increments),
  dashboardTrackersRefreshStorage: (): Promise<import('../shared/dashboardTrackers').DashboardTrackers> =>
    ipcRenderer.invoke('dashboardTrackers:refreshStorage'),
  dashboardTrackersSyncAfterJob: (
    outputDir: string
  ): Promise<import('../shared/dashboardTrackers').DashboardTrackers> =>
    ipcRenderer.invoke('dashboardTrackers:syncAfterJob', outputDir),
  onDashboardTrackersUpdated: (
    callback: (data: import('../shared/dashboardTrackers').DashboardTrackers) => void
  ) => {
    const handler = (_event: unknown, payload: import('../shared/dashboardTrackers').DashboardTrackers) =>
      callback(payload)
    ipcRenderer.on('dashboard-trackers:updated', handler)
    return (): void => {
      ipcRenderer.removeListener('dashboard-trackers:updated', handler)
    }
  },
}

// Expose the API to the renderer process
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electronAPI', api)
  } catch (error) {
    console.error('Failed to expose API:', error)
  }
} else {
  ;(window as unknown as { electronAPI: typeof api }).electronAPI = api
}

// Type definitions for TypeScript support in renderer
declare global {
  interface Window {
    electronAPI: typeof api
  }
}

export type ElectronAPI = typeof api
