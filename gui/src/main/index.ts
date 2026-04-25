import { app, shell, BrowserWindow, ipcMain, dialog, protocol, Menu } from 'electron'
import { createRequire } from 'node:module'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { pythonBridge } from './python-bridge'
import { devLogLine } from './dev-logger'
import { setupAppMediaProtocol } from './media-serve'
import { discoverScrapeOutputs, listOutputDownloadMedia, readOutputArtifact, readOutputVideoMeta } from './output-read'

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

function createWindow(): void {
  devLogLine(
    `createWindow: is.dev=${is.dev} ELECTRON_RENDERER_URL=${process.env['ELECTRON_RENDERER_URL'] ?? 'none'}`
  )

  // Create the browser window
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    show: false,
    frame: false,
    autoHideMenuBar: true,
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
    void pythonBridge.start().then((result) => {
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

// App event handlers
app.whenReady().then(() => {
  devLogLine(`app whenReady: version=${app.getVersion()} userData=${app.getPath('userData')}`)

  setupAppMediaProtocol(store)
  Menu.setApplicationMenu(null)

  // Set app user model id for Windows
  electronApp.setAppUserModelId('com.electron.youtube-scrape')

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // IPC handlers for Python server
  ipcMain.handle('python:start', async () => {
    return await pythonBridge.start()
  })

  ipcMain.handle('python:stop', async () => {
    return await pythonBridge.stop()
  })

  ipcMain.handle('python:status', () => {
    return pythonBridge.getStatus()
  })

  // Forward Python logs to renderer
  pythonBridge.onLog((log) => {
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
