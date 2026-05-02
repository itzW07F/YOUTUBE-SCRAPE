import { app, shell, BrowserWindow, ipcMain, dialog, protocol, Menu } from 'electron'
import { createRequire } from 'node:module'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { pythonBridge, youtubeScrapeSpawnEnvExtras } from './python-bridge'
import { devLogLine } from './dev-logger'
import { appendAppFileLog, getAppLogDirectory } from './app-file-logger'
import { setupAppMediaProtocol, getAllowedOutputRoots } from './media-serve'
import {
  applyDashboardTrackerIncrements,
  flushDashboardTrackers,
  readDashboardTrackers,
  refreshDashboardStorage,
  syncDashboardAfterJob,
} from './dashboard-trackers-file'
import type {
  DashboardTrackers,
  DashboardTrackerIncrements,
} from '../shared/dashboardTrackers'
import {
  deleteOutputScrapeDir,
  discoverScrapeOutputs,
  listOutputDownloadMedia,
  readOutputArtifact,
  readOutputVideoMeta,
} from './output-read'
import {
  createAnalyticsUserNote,
  deleteAnalyticsUserNote,
  listAnalyticsUserNotes,
  readAnalyticsUserNote,
  renameAnalyticsUserNote,
  writeAnalyticsUserNote,
} from './analytics-user-notes'

// electron-store@10 is ESM-only; bundled CJS `require` yields `{ default: Store }` under Electron.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const require = createRequire(import.meta.url)
// eslint-disable-next-line @typescript-eslint/no-var-requires, @typescript-eslint/no-require-imports
const EStore = require('electron-store') as { default: new () => import('electron-store') }
const Store = EStore.default
// Disable sandbox on Linux for development (fixes chrome-sandbox permission issues)
if (process.platform === 'linux') {
  app.commandLine.appendSwitch('--no-sandbox')
  app.commandLine.appendSwitch('--disable-setuid-sandbox')
}

// Optional: blank window / full-GPU freeze on some Linux stacks (set ELECTRON_DISABLE_GPU=1)
if (process.env.ELECTRON_DISABLE_GPU === '1') {
  app.disableHardwareAcceleration()
}

protocol.registerSchemesAsPrivileged([
  {
    scheme: 'appmedia',
    privileges: {
      standard: true,
      secure: true,
      supportFetch: true,
      corsEnabled: true,
      stream: true
    }
  }
])

// Initialize store for persistent settings
const store = new Store()

// Keep track of window state
let mainWindow: BrowserWindow | null = null

/** Narrowest width where sidebar + jobs header/actions stay usable (no overlapping controls). Tune if layout changes. */
const MAIN_WINDOW_MIN_WIDTH = 1200

/** Shortest height before content/layout feels cramped. Tune after manual resize testing. */
const MAIN_WINDOW_MIN_HEIGHT = 900

function createWindow(): void {
  devLogLine(
    `createWindow: is.dev=${is.dev} ELECTRON_RENDERER_URL=${process.env['ELECTRON_RENDERER_URL'] ?? 'none'}`
  )

  // Create the browser window (opens at minimum usable size, centered on the primary display)
  mainWindow = new BrowserWindow({
    width: MAIN_WINDOW_MIN_WIDTH,
    height: MAIN_WINDOW_MIN_HEIGHT,
    minWidth: MAIN_WINDOW_MIN_WIDTH,
    minHeight: MAIN_WINDOW_MIN_HEIGHT,
    center: true,
    show: false,
    frame: false,
    autoHideMenuBar: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true
    },
    backgroundColor: '#0a0a0f'
  })

  // Load the app
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  const wc = mainWindow.webContents
  wc.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    devLogLine(`did-fail-load: code=${errorCode} desc=${String(errorDescription)} url=${validatedURL}`)
  })
  wc.on('console-message', (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      devLogLine(`renderer console [${level}]: ${String(message)} (${sourceId}:${line})`)
    }
  })
  wc.on('did-finish-load', () => {
    devLogLine('renderer did-finish-load')
  })

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()

    devLogLine(`python spawn context: ${JSON.stringify(pythonBridge.getSpawnContextForLog())}`)

    // Start Python server automatically
    void pythonBridge
      .start(getAllowedOutputRoots(store), youtubeScrapeSpawnEnvExtras(store))
      .then((result) => {
        devLogLine(`pythonBridge.start result: ${JSON.stringify(result)}`)
        if (!result.success) {
          console.error('Failed to start Python server:', result.error)
        }
      })
  })

  // Handle window state changes
  mainWindow.on('maximize', () => {
    mainWindow?.webContents.send('window:state-changed', { isMaximized: true })
  })

  mainWindow.on('unmaximize', () => {
    mainWindow?.webContents.send('window:state-changed', { isMaximized: false })
  })

  // Handle window closed
  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function broadcastDashboardTrackers(data: DashboardTrackers): void {
  for (const w of BrowserWindow.getAllWindows()) {
    if (w.isDestroyed()) {
      continue
    }
    w.webContents.send('dashboard-trackers:updated', data)
  }
}

function buildApplicationMenu(): Menu {
  const template: Electron.MenuItemConstructorOptions[] = []
  if (process.platform === 'darwin') {
    template.push({
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    })
  }
  template.push({
    label: 'File',
    submenu: [
      {
        label: 'Flush Dashboard Trackers…',
        click: async () => {
          const win = BrowserWindow.getFocusedWindow() ?? mainWindow
          if (!win) {
            return
          }
          const { response } = await dialog.showMessageBox(win, {
            type: 'warning',
            buttons: ['Cancel', 'Flush'],
            defaultId: 0,
            cancelId: 0,
            title: 'Flush dashboard trackers',
            message: 'Reset lifetime scrape and comment totals?',
            detail:
              'Total storage is recalculated from your configured output folders. Jobs, results, and files are not removed.',
          })
          if (response !== 1) {
            return
          }
          const next = flushDashboardTrackers(store)
          broadcastDashboardTrackers(next)
        },
      },
      ...(process.platform === 'darwin'
        ? []
        : ([
            { type: 'separator' },
            { role: 'quit' },
          ] as Electron.MenuItemConstructorOptions[])),
    ],
  })
  return Menu.buildFromTemplate(template)
}

// App event handlers
app.whenReady().then(() => {
  devLogLine(`app whenReady: version=${app.getVersion()} userData=${app.getPath('userData')}`)

  setupAppMediaProtocol(store)
  Menu.setApplicationMenu(buildApplicationMenu())

  // Set app user model id for Windows
  electronApp.setAppUserModelId('com.electron.youtube-scrape')

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // IPC handlers for Python server
  ipcMain.handle('python:start', async () => {
    return await pythonBridge.start(getAllowedOutputRoots(store), youtubeScrapeSpawnEnvExtras(store))
  })

  ipcMain.handle('python:restart', async () => {
    await pythonBridge.stop()
    await new Promise((r) => setTimeout(r, 400))
    return pythonBridge.start(getAllowedOutputRoots(store), youtubeScrapeSpawnEnvExtras(store))
  })

  ipcMain.handle('python:stop', async () => {
    return await pythonBridge.stop()
  })

  ipcMain.handle('python:status', () => {
    return pythonBridge.getStatus()
  })

  // Forward Python logs to renderer
  pythonBridge.onLog((log) => {
    appendAppFileLog('python', log.level, log.message)
    mainWindow?.webContents.send('python:log', log)
  })

  // IPC handlers for file system operations
  ipcMain.handle('dialog:selectDirectory', async () => {
    if (!mainWindow) return { canceled: true, filePaths: [] }
    return await dialog.showOpenDialog(mainWindow, {
      properties: ['openDirectory', 'createDirectory']
    })
  })

  ipcMain.handle('dialog:selectFile', async (_, filters) => {
    if (!mainWindow) return { canceled: true, filePaths: [] }
    return await dialog.showOpenDialog(mainWindow, {
      properties: ['openFile'],
      filters: filters || [{ name: 'All Files', extensions: ['*'] }]
    })
  })

  ipcMain.handle('shell:openPath', async (_, path: string) => {
    return await shell.openPath(path)
  })

  ipcMain.handle('shell:showItemInFolder', async (_, path: string) => {
    await shell.showItemInFolder(path)
  })

  ipcMain.handle('shell:openExternal', async (_, url: string) => {
    const u = typeof url === 'string' ? url.trim() : ''
    if (!/^https?:\/\//i.test(u)) {
      return { ok: false as const, error: 'Only http(s) URLs are allowed' }
    }
    try {
      await shell.openExternal(u)
      return { ok: true as const }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      return { ok: false as const, error: msg }
    }
  })

  // IPC handlers for app info
  ipcMain.handle('app:version', () => {
    return app.getVersion()
  })

  ipcMain.handle('app:platform', () => {
    return process.platform
  })

  ipcMain.handle('app:runtime', () => {
    return {
      arch: process.arch,
      node: process.versions.node,
      electron: process.versions.electron
    }
  })

  ipcMain.handle(
    'app:appendLog',
    (
      _,
      payload: { level?: string; scope?: string; message?: string; detail?: unknown }
    ) => {
      const msg = payload?.message
      if (typeof msg !== 'string') {
        return
      }
      const scope = typeof payload.scope === 'string' ? payload.scope : 'renderer'
      const level = typeof payload.level === 'string' ? payload.level : 'info'
      appendAppFileLog('renderer', level, `[${scope}] ${msg}`, payload.detail)
    }
  )

  ipcMain.handle('app:logDirectory', () => getAppLogDirectory())

  ipcMain.handle('output:readVideoMeta', (_, outputDir: string) => {
    return readOutputVideoMeta(outputDir, store)
  })

  ipcMain.handle('output:listMediaFiles', (_, outputDir: string) => {
    return listOutputDownloadMedia(outputDir, store)
  })

  ipcMain.handle('output:readArtifact', (_, outputDir: string, kind: Parameters<typeof readOutputArtifact>[1]) => {
    return readOutputArtifact(outputDir, kind, store)
  })

  ipcMain.handle('output:discoverScrapes', () => {
    return discoverScrapeOutputs(store)
  })

  ipcMain.handle('output:deleteScrapeDir', (_, outputDir: string) => {
    return deleteOutputScrapeDir(outputDir, store)
  })

  ipcMain.handle('analyticsNotes:list', (_, outputDir: string) => {
    const r = listAnalyticsUserNotes(outputDir, store)
    if (!r.ok) {
      return { ok: false as const, error: r.error }
    }
    return { ok: true as const, files: r.data.files }
  })

  ipcMain.handle('analyticsNotes:read', (_, outputDir: string, fileId: string) => {
    const r = readAnalyticsUserNote(outputDir, fileId, store)
    if (!r.ok) {
      return { ok: false as const, error: r.error }
    }
    return { ok: true as const, content: r.data.content }
  })

  ipcMain.handle('analyticsNotes:write', (_, outputDir: string, fileId: string, content: string) => {
    const r = writeAnalyticsUserNote(outputDir, fileId, content, store)
    if (!r.ok) {
      return { ok: false as const, error: r.error }
    }
    return { ok: true as const }
  })

  ipcMain.handle('analyticsNotes:create', (_, outputDir: string, displayName: string | undefined) => {
    const r = createAnalyticsUserNote(outputDir, displayName, store)
    if (!r.ok) {
      return { ok: false as const, error: r.error }
    }
    return { ok: true as const, file: r.data.file }
  })

  ipcMain.handle('analyticsNotes:delete', (_, outputDir: string, fileId: string) => {
    const r = deleteAnalyticsUserNote(outputDir, fileId, store)
    if (!r.ok) {
      return { ok: false as const, error: r.error }
    }
    return { ok: true as const, files: r.data.files }
  })

  ipcMain.handle('analyticsNotes:rename', (_, outputDir: string, fileId: string, displayName: string) => {
    const r = renameAnalyticsUserNote(outputDir, fileId, displayName, store)
    if (!r.ok) {
      return { ok: false as const, error: r.error }
    }
    return { ok: true as const, file: r.data.file }
  })

  // IPC handlers for window controls
  ipcMain.handle('window:minimize', () => {
    mainWindow?.minimize()
  })

  ipcMain.handle('window:maximize', () => {
    if (mainWindow?.isMaximized()) {
      mainWindow.unmaximize()
    } else {
      mainWindow?.maximize()
    }
  })

  ipcMain.handle('window:close', () => {
    mainWindow?.close()
  })

  ipcMain.handle('window:isMaximized', () => {
    return mainWindow?.isMaximized() || false
  })

  // IPC handlers for store operations
  ipcMain.handle('store:get', (_, key: string) => {
    return store.get(key)
  })

  ipcMain.handle('store:set', (_, key: string, value: unknown) => {
    store.set(key, value)
  })

  ipcMain.handle('store:delete', (_, key: string) => {
    store.delete(key)
  })

  ipcMain.handle('dashboardTrackers:get', () => {
    return readDashboardTrackers()
  })

  ipcMain.handle('dashboardTrackers:applyIncrements', (_, increments: DashboardTrackerIncrements) => {
    const next = applyDashboardTrackerIncrements(increments)
    broadcastDashboardTrackers(next)
    return next
  })

  ipcMain.handle('dashboardTrackers:refreshStorage', () => {
    const next = refreshDashboardStorage(store)
    broadcastDashboardTrackers(next)
    return next
  })

  ipcMain.handle('dashboardTrackers:syncAfterJob', (_, outputDir: string) => {
    const next = syncDashboardAfterJob(outputDir, store)
    broadcastDashboardTrackers(next)
    return next
  })

  // Create window
  createWindow()

  app.on('activate', () => {
    // On macOS, re-create window when dock icon is clicked
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

// Single shutdown path: avoid before-quit → preventDefault → app.quit() → before-quit loop (CPU lockup).
let isQuitting = false
app.on('before-quit', (event) => {
  if (isQuitting) {
    return
  }
  event.preventDefault()
  isQuitting = true
  void pythonBridge.stop().finally(() => {
    app.exit(0)
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// Security: Prevent new window creation
app.on('web-contents-created', (_, contents) => {
  contents.on('new-window', (event) => {
    event.preventDefault()
  })
})
