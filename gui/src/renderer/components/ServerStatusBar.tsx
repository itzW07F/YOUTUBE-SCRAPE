import React from 'react'
import { motion } from 'framer-motion'
import { Wifi, WifiOff, Activity } from 'lucide-react'

interface ServerStatusBarProps {
  isRunning: boolean
}

const ServerStatusBar: React.FC<ServerStatusBarProps> = ({ isRunning }) => {
  return (
    <div className="h-8 flex items-center justify-between px-4 bg-space-900 border-t border-glass-border text-xs">
      <div className="flex items-center gap-4">
        {/* Server status */}
        <div className="flex items-center gap-2">
          {isRunning ? (
            <>
              <motion.div
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ duration: 2, repeat: Infinity }}
                className="w-2 h-2 rounded-full bg-neon-green"
              />
              <Wifi className="w-3.5 h-3.5 text-neon-green" />
              <span className="text-space-200">API Server Connected</span>
            </>
          ) : (
            <>
              <div className="w-2 h-2 rounded-full bg-rose-500" />
              <WifiOff className="w-3.5 h-3.5 text-rose-500" />
              <span className="text-rose-400">API Server Disconnected</span>
            </>
          )}
        </div>

        {/* System info */}
        <div className="flex items-center gap-2 text-space-400">
          <Activity className="w-3.5 h-3.5" />
          <span>Ready</span>
        </div>
      </div>

      <div className="flex items-center gap-4 text-space-400">
        <span>Electron + React + Python</span>
        <span className="text-space-600">|</span>
        <span className="text-neon-blue">YouTube Scrape Pro</span>
      </div>
    </div>
  )
}

export default ServerStatusBar
