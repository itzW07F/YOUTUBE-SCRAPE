import React, { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import {
  Terminal,
  Trash2,
  Download,
  Wifi,
  WifiOff,
  RefreshCw,
  Send,
  FolderOpen,
} from 'lucide-react'
import { useAppStore } from '../stores/appStore'

interface LogEntry {
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
  timestamp: string
  source: 'python' | 'electron' | 'renderer'
}

const DebugView: React.FC = () => {
  const { isServerRunning, serverUrl } = useAppStore()
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [filter, setFilter] = useState<'all' | 'python' | 'electron'>('all')
  const [isConnected, setIsConnected] = useState(false)
  const [apiResponse, setApiResponse] = useState<string>('')
  const [testEndpoint, setTestEndpoint] = useState('/health')
  const [persistentLogDir, setPersistentLogDir] = useState<string>('')
  const logsEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void window.electronAPI.getAppLogDirectory().then((dir) => {
      if (typeof dir === 'string' && dir.length > 0) {
        setPersistentLogDir(dir)
      }
    })
  }, [])

  useEffect(() => {
    // Subscribe to Python server logs
    const unsubscribe = window.electronAPI.onServerLog((_, log) => {
      setLogs((prev) => [
        ...prev,
        {
          level: log.level as LogEntry['level'],
          message: log.message,
          timestamp: log.timestamp,
          source: 'python' as const,
        },
      ])
    })

    return () => {
      unsubscribe()
    }
  }, [])

  useEffect(() => {
    // Auto-scroll to bottom
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  useEffect(() => {
    setIsConnected(isServerRunning)
  }, [isServerRunning])

  const handleClearLogs = () => {
    setLogs([])
  }

  const handleExportLogs = () => {
    const content = logs
      .map((log) => `[${log.timestamp}] [${log.source}] [${log.level}] ${log.message}`)
      .join('\n')
    
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `debug-logs-${new Date().toISOString()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleTestApi = async () => {
    if (!serverUrl) return
    
    try {
      const response = await fetch(`${serverUrl}${testEndpoint}`)
      const data = await response.json()
      setApiResponse(JSON.stringify(data, null, 2))
    } catch (error) {
      setApiResponse(`Error: ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  const handleRestartServer = async () => {
    await window.electronAPI.stopPythonServer()
    await new Promise((resolve) => setTimeout(resolve, 1000))
    const result = await window.electronAPI.startPythonServer()
    if (result.success) {
      setLogs((prev) => [
        ...prev,
        {
          level: 'info',
          message: 'Server restarted successfully',
          timestamp: new Date().toISOString(),
          source: 'electron',
        },
      ])
    } else {
      setLogs((prev) => [
        ...prev,
        {
          level: 'error',
          message: `Failed to restart server: ${result.error}`,
          timestamp: new Date().toISOString(),
          source: 'electron',
        },
      ])
    }
  }

  const filteredLogs = logs.filter((log) => filter === 'all' || log.source === filter)

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-display font-bold text-white">Debug Console</h2>
          <p className="text-space-400">Monitor logs and test API endpoints</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm ${
            isConnected ? 'bg-neon-green/10 text-neon-green' : 'bg-rose-500/10 text-rose-500'
          }`}>
            {isConnected ? <Wifi className="w-4 h-4" /> : <WifiOff className="w-4 h-4" />}
            {isConnected ? 'Connected' : 'Disconnected'}
          </div>
          <button
            onClick={handleRestartServer}
            className="p-2 rounded-lg hover:bg-white/5 text-space-400 hover:text-white transition-colors"
            title="Restart Python server"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            onClick={handleExportLogs}
            className="p-2 rounded-lg hover:bg-white/5 text-space-400 hover:text-white transition-colors"
            title="Export logs"
          >
            <Download className="w-4 h-4" />
          </button>
          <button
            onClick={handleClearLogs}
            className="p-2 rounded-lg hover:bg-rose-500/10 text-space-400 hover:text-rose-400 transition-colors"
            title="Clear logs"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-4">
        {(['all', 'python', 'electron'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`
              px-4 py-2 rounded-lg text-sm font-medium transition-colors
              ${filter === f
                ? 'bg-neon-blue/20 text-neon-blue'
                : 'bg-white/5 text-space-400 hover:text-white hover:bg-white/[0.07]'
              }
            `}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {persistentLogDir ? (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-card p-4 mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="min-w-0">
            <p className="text-sm font-medium text-white">Persistent log files</p>
            <p className="mt-1 break-all font-mono text-xs text-space-400">{persistentLogDir}</p>
            <p className="mt-1 text-xs text-space-500">
              Daily files: youtube-scrape-YYYY-MM-DD.log (main, renderer, and Python process output).
            </p>
          </div>
          <button
            type="button"
            onClick={() => void window.electronAPI.openPath(persistentLogDir)}
            className="futuristic-btn flex shrink-0 items-center gap-2 self-start sm:self-center"
          >
            <FolderOpen className="h-4 w-4" />
            Open folder
          </button>
        </motion.div>
      ) : null}

      {/* API Tester */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card p-4 mb-4"
      >
        <div className="flex items-center gap-3 mb-3">
          <Terminal className="w-5 h-5 text-neon-blue" />
          <h3 className="font-semibold text-white">API Tester</h3>
        </div>
        <div className="flex gap-3">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="text-neon-blue">{serverUrl || 'http://localhost:8000'}</span>
              <input
                type="text"
                value={testEndpoint}
                onChange={(e) => setTestEndpoint(e.target.value)}
                className="futuristic-input flex-1 px-3 py-2"
                placeholder="/health"
              />
            </div>
          </div>
          <button
            onClick={handleTestApi}
            disabled={!serverUrl}
            className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
            Send
          </button>
        </div>
        {apiResponse && (
          <pre className="mt-3 code-block p-3 text-xs overflow-auto max-h-40">
            {apiResponse}
          </pre>
        )}
      </motion.div>

      {/* Logs */}
      <div className="flex-1 glass-card overflow-hidden flex flex-col">
        <div className="p-3 border-b border-glass-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-space-400" />
            <span className="text-sm text-space-300">Logs ({filteredLogs.length} entries)</span>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-4 space-y-1 font-mono text-sm">
          {filteredLogs.length === 0 ? (
            <div className="text-center py-8 text-space-500">
              <p>No logs yet...</p>
              <p className="text-xs mt-1">Logs will appear here when the server starts</p>
            </div>
          ) : (
            filteredLogs.map((log, index) => {
              const isError = log.level === 'error'
              const isWarn = log.level === 'warn'
              
              return (
                <div
                  key={index}
                  className={`
                    flex gap-3 py-1 border-l-2 pl-3 -ml-3
                    ${isError ? 'border-rose-500 bg-rose-500/5' :
                      isWarn ? 'border-amber-500 bg-amber-500/5' :
                      'border-transparent hover:bg-white/[0.02]'}
                  `}
                >
                  <span className="text-space-500 text-xs whitespace-nowrap">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>
                  <span className={`
                    text-xs font-medium uppercase w-16
                    ${log.source === 'python' ? 'text-neon-blue' :
                      log.source === 'electron' ? 'text-neon-purple' :
                      'text-space-400'}
                  `}>
                    {log.source}
                  </span>
                  <span className={`
                    text-xs font-medium uppercase w-12
                    ${isError ? 'text-rose-400' :
                      isWarn ? 'text-amber-400' :
                      'text-space-400'}
                  `}>
                    {log.level}
                  </span>
                  <span className={`${isError ? 'text-rose-300' : 'text-space-200'}`}>
                    {log.message}
                  </span>
                </div>
              )
            })
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  )
}

export default DebugView
