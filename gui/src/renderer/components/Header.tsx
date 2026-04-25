import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Minus,
  Square,
  X,
  Moon,
  Sun,
} from 'lucide-react'
import { useAppStore } from '../stores/appStore'

interface HeaderProps {
  currentView: string
}

const viewTitles: Record<string, string> = {
  dashboard: 'Dashboard',
  scrape: 'New Scrape',
  jobs: 'Job Monitor',
  results: 'Results',
  gallery: 'Video Gallery',
  settings: 'Settings',
  debug: 'Debug Console',
}

const Header: React.FC<HeaderProps> = ({ currentView }) => {
  const { isDarkMode, setDarkMode } = useAppStore()
  const [appVersion, setAppVersion] = useState('1.0.0')

  useEffect(() => {
    if (!window.electronAPI) {
      return
    }
    void window.electronAPI
      .getAppVersion()
      .then((v) => setAppVersion(v))
      .catch(() => {
        setAppVersion('1.0.0')
      })
  }, [])

  const handleMinimize = () => {
    window.electronAPI.minimizeWindow()
  }

  const handleMaximize = () => {
    window.electronAPI.maximizeWindow()
  }

  const handleClose = () => {
    window.electronAPI.closeWindow()
  }

  return (
    <header
      className="h-14 flex items-center justify-between px-6 border-b border-glass-border bg-space-800/30 backdrop-blur-lg app-region-drag"
    >
      {/* Title */}
      <div className="flex items-center gap-4">
        <h2 className="text-lg font-display font-semibold text-white">
          {viewTitles[currentView] || 'YouTube Scrape'}
        </h2>
        <span className="text-xs px-2 py-1 rounded-full bg-neon-blue/10 text-neon-blue border border-neon-blue/20">
          v{appVersion}
        </span>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3 app-region-no-drag">
        {/* Theme toggle */}
        <button
          onClick={() => setDarkMode(!isDarkMode)}
          className="p-2 rounded-lg text-space-300 hover:text-white hover:bg-white/5 transition-colors"
          title={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {isDarkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>

        {/* Window controls */}
        <div className="flex items-center gap-1 ml-2 pl-3 border-l border-glass-border">
          <motion.button
            whileHover={{ scale: 1.1 }}
            onClick={handleMinimize}
            className="p-2 rounded-lg text-space-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            <Minus className="w-4 h-4" />
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.1 }}
            onClick={handleMaximize}
            className="p-2 rounded-lg text-space-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            <Square className="w-4 h-4" />
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.1 }}
            onClick={handleClose}
            className="p-2 rounded-lg text-space-400 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
          >
            <X className="w-4 h-4" />
          </motion.button>
        </div>
      </div>
    </header>
  )
}

export default Header
