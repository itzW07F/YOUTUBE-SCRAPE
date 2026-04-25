import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  FolderOpen,
  Moon,
  Sun,
  Monitor,
  Save,
  RotateCcw,
  Check,
  AlertCircle,
  FileCode,
  HardDrive,
} from 'lucide-react'
import {
  useAppStore,
  UI_FONT_SIZE_MIN,
  UI_FONT_SIZE_MAX,
  UI_FONT_SIZE_DEFAULT,
} from '../stores/appStore'
import toast from 'react-hot-toast'

const SettingsView: React.FC = () => {
  const { isDarkMode, setDarkMode, outputDirectory, setOutputDirectory, uiFontSizePercent, setUiFontSizePercent } =
    useAppStore()
  const [pythonPath, setPythonPath] = useState('')
  const [isCheckingPython, setIsCheckingPython] = useState(false)
  const [pythonStatus, setPythonStatus] = useState<'ok' | 'error' | null>(null)
  const [appVersion, setAppVersion] = useState('')
  const [platform, setPlatform] = useState('')
  const [nodeArch, setNodeArch] = useState('—')
  const [nodeVersion, setNodeVersion] = useState('—')
  const [electronVersion, setElectronVersion] = useState('—')

  useEffect(() => {
    if (!window.electronAPI) {
      return
    }
    void window.electronAPI.getAppVersion().then(setAppVersion).catch(() => setAppVersion(''))
    void window.electronAPI.getPlatform().then(setPlatform).catch(() => setPlatform(''))
    void window.electronAPI
      .storeGet('pythonPath')
      .then((path) => {
        if (path) {
          setPythonPath(path as string)
        }
      })
      .catch(() => {
        // ignore
      })
    void window.electronAPI
      .getAppRuntime()
      .then((r) => {
        setNodeArch(r.arch)
        setNodeVersion(r.node)
        setElectronVersion(r.electron)
      })
      .catch(() => {
        // ignore
      })
  }, [])

  const handleSelectOutputDir = async () => {
    const result = await window.electronAPI.selectDirectory()
    if (!result.canceled && result.filePaths.length > 0) {
      setOutputDirectory(result.filePaths[0])
      toast.success('Output directory updated')
    }
  }

  const handleSavePythonPath = async () => {
    await window.electronAPI.storeSet('pythonPath', pythonPath)
    toast.success('Python path saved')
  }

  const handleCheckPython = async () => {
    setIsCheckingPython(true)
    // In a real implementation, we'd verify the Python path
    setTimeout(() => {
      setPythonStatus('ok')
      setIsCheckingPython(false)
    }, 1000)
  }

  const handleResetSettings = async () => {
    if (confirm('Are you sure you want to reset all settings to defaults?')) {
      await window.electronAPI.storeSet('outputDirectory', '')
      await window.electronAPI.storeSet('pythonPath', '')
      await window.electronAPI.storeSet('uiFontSizePercent', UI_FONT_SIZE_DEFAULT)
      setOutputDirectory('')
      setPythonPath('')
      setUiFontSizePercent(UI_FONT_SIZE_DEFAULT)
      toast.success('Settings reset to defaults')
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="mb-6">
        <h2 className="text-2xl font-display font-bold text-white">Settings</h2>
        <p className="text-space-400">Configure your scraping preferences</p>
      </div>

      {/* Appearance */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card p-6"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-neon-purple/10 flex items-center justify-center">
            <Monitor className="w-5 h-5 text-neon-purple" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Appearance</h3>
            <p className="text-sm text-space-400">Customize the visual theme and text size</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={() => setDarkMode(false)}
            className={`
              flex-1 flex items-center gap-3 p-4 rounded-xl border transition-all
              ${!isDarkMode
                ? 'bg-neon-blue/10 border-neon-blue/40 text-white'
                : 'bg-white/5 border-glass-border text-space-300 hover:bg-white/[0.07]'
              }
            `}
          >
            <Sun className={`w-5 h-5 ${!isDarkMode ? 'text-neon-blue' : ''}`} />
            <span>Light Mode</span>
          </button>
          <button
            onClick={() => setDarkMode(true)}
            className={`
              flex-1 flex items-center gap-3 p-4 rounded-xl border transition-all
              ${isDarkMode
                ? 'bg-neon-blue/10 border-neon-blue/40 text-white'
                : 'bg-white/5 border-glass-border text-space-300 hover:bg-white/[0.07]'
              }
            `}
          >
            <Moon className={`w-5 h-5 ${isDarkMode ? 'text-neon-blue' : ''}`} />
            <span>Dark Mode</span>
          </button>
        </div>

        <div className="mt-6 pt-6 border-t border-glass-border/80">
          <p className="text-sm font-medium text-white mb-1">Text size</p>
          <p className="text-xs text-space-400 mb-4">Scales the interface. Uses rem so most UI updates together.</p>
          <div className="flex items-center gap-3">
            <span className="text-xs text-space-500 w-8 shrink-0">{UI_FONT_SIZE_MIN}%</span>
            <input
              type="range"
              min={UI_FONT_SIZE_MIN}
              max={UI_FONT_SIZE_MAX}
              step={5}
              value={uiFontSizePercent}
              onChange={(e) => setUiFontSizePercent(Number(e.target.value))}
              className="flex-1 h-2 rounded-full accent-cyan-500"
              aria-label="Interface text size"
            />
            <span className="text-xs text-space-500 w-8 shrink-0 text-right">{UI_FONT_SIZE_MAX}%</span>
          </div>
          <p className="text-center text-sm text-neon-cyan font-medium tabular-nums mt-2">{uiFontSizePercent}%</p>
          <div className="flex flex-wrap justify-center gap-2 mt-3">
            {(
              [
                { label: 'Small', v: 90 },
                { label: 'Default', v: 100 },
                { label: 'Large', v: 115 },
                { label: 'Extra', v: 130 },
              ] as const
            ).map((p) => (
              <button
                key={p.v}
                type="button"
                onClick={() => setUiFontSizePercent(p.v)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                  uiFontSizePercent === p.v
                    ? 'border-neon-blue/50 bg-neon-blue/10 text-white'
                    : 'border-glass-border text-space-300 hover:bg-white/5'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </motion.div>

      {/* Output Directory */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass-card p-6"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-neon-green/10 flex items-center justify-center">
            <FolderOpen className="w-5 h-5 text-neon-green" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Output Directory</h3>
            <p className="text-sm text-space-400">Where scraped data will be saved</p>
          </div>
        </div>

        <div className="flex gap-3">
          <div className="flex-1 futuristic-input flex items-center px-4 py-3">
            <HardDrive className="w-5 h-5 text-space-400 mr-3" />
            <span className="text-space-300 truncate">
              {outputDirectory || 'Default (./output)'}
            </span>
          </div>
          <button
            onClick={handleSelectOutputDir}
            className="futuristic-btn flex items-center gap-2 px-6"
          >
            <FolderOpen className="w-4 h-4" />
            Browse
          </button>
        </div>
      </motion.div>

      {/* Python Configuration */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="glass-card p-6"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-neon-blue/10 flex items-center justify-center">
            <FileCode className="w-5 h-5 text-neon-blue" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Python Configuration</h3>
            <p className="text-sm text-space-400">Path to Python executable (optional)</p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <input
                type="text"
                value={pythonPath}
                onChange={(e) => setPythonPath(e.target.value)}
                placeholder="Auto-detected"
                className="futuristic-input w-full px-4 py-3"
              />
              {pythonStatus === 'ok' && (
                <Check className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-neon-green" />
              )}
            </div>
            <button
              onClick={handleCheckPython}
              disabled={isCheckingPython || !pythonPath}
              className="futuristic-btn flex items-center gap-2 px-4"
            >
              {isCheckingPython ? (
                <div className="w-4 h-4 border-2 border-neon-blue/30 border-t-neon-blue rounded-full animate-spin" />
              ) : (
                <Check className="w-4 h-4" />
              )}
              Test
            </button>
            <button
              onClick={handleSavePythonPath}
              disabled={!pythonPath}
              className="futuristic-btn futuristic-btn-primary flex items-center gap-2 px-4"
            >
              <Save className="w-4 h-4" />
              Save
            </button>
          </div>

          {pythonStatus === 'error' && (
            <p className="text-sm text-rose-400 flex items-center gap-1">
              <AlertCircle className="w-4 h-4" />
              Python not found at this path
            </p>
          )}
        </div>
      </motion.div>

      {/* Application Info */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="glass-card p-6"
      >
        <h3 className="font-semibold text-white mb-4">Application Info</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-space-400">Version</p>
            <p className="text-white">{appVersion}</p>
          </div>
          <div>
            <p className="text-space-400">Platform</p>
            <p className="text-white capitalize">{platform}</p>
          </div>
          <div>
            <p className="text-space-400">Architecture</p>
            <p className="text-white">{nodeArch}</p>
          </div>
          <div>
            <p className="text-space-400">Node / Electron</p>
            <p className="text-white">
              Node {nodeVersion}
              {electronVersion !== '—' && (
                <span className="text-space-400"> · Electron {electronVersion}</span>
              )}
            </p>
          </div>
        </div>
      </motion.div>

      {/* Keyboard Shortcuts */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35 }}
        className="glass-card p-6"
      >
        <h3 className="font-semibold text-white mb-4">Keyboard Shortcuts</h3>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <ShortcutItem shortcut="⌘N" description="New Scrape" />
          <ShortcutItem shortcut="⌘J" description="Open Jobs" />
          <ShortcutItem shortcut="⌘R" description="Open Results" />
          <ShortcutItem shortcut="⌘," description="Open Settings" />
          <ShortcutItem shortcut="⌘D" description="Open Debug" />
          <ShortcutItem shortcut="⌘⇧L" description="Toggle Theme" />
          <ShortcutItem shortcut="⌘F" description="Search" />
          <ShortcutItem shortcut="Esc" description="Go Back" />
        </div>
        <p className="text-xs text-space-400 mt-3">
          On Windows/Linux, use Ctrl instead of ⌘
        </p>
      </motion.div>

      {/* Reset */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="flex justify-end"
      >
        <button
          onClick={handleResetSettings}
          className="flex items-center gap-2 text-rose-400 hover:text-rose-300 transition-colors"
        >
          <RotateCcw className="w-4 h-4" />
          Reset all settings to defaults
        </button>
      </motion.div>
    </div>
  )
}

const ShortcutItem: React.FC<{ shortcut: string; description: string }> = ({
  shortcut,
  description,
}) => (
  <div className="flex items-center justify-between py-2 border-b border-glass-border last:border-0">
    <span className="text-space-300">{description}</span>
    <kbd className="px-2 py-1 rounded bg-space-700 text-neon-cyan font-mono text-xs">
      {shortcut}
    </kbd>
  </div>
)

export default SettingsView
