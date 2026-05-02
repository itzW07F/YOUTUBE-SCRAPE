import React from 'react'
import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  Clapperboard,
  Play,
  ListTodo,
  FolderOpen,
  Settings,
  Terminal,
  Youtube,
  BarChart3,
} from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'

type SidebarViewId =
  | 'dashboard'
  | 'scrape'
  | 'jobs'
  | 'results'
  | 'gallery'
  | 'analytics'
  | 'settings'
  | 'debug'

interface SidebarProps {
  currentView: string
  onNavigate: (view: SidebarViewId, options?: { preserveScrapeOptions?: boolean }) => void
}

const navItems: Array<{ id: SidebarViewId; label: string; icon: typeof LayoutDashboard }> = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'scrape', label: 'New Scrape', icon: Play },
  { id: 'jobs', label: 'Scrape Jobs', icon: ListTodo },
  { id: 'results', label: 'Results', icon: FolderOpen },
  { id: 'gallery', label: 'Video Gallery', icon: Clapperboard },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
  { id: 'debug', label: 'Debug', icon: Terminal },
]

const Sidebar: React.FC<SidebarProps> = ({ currentView, onNavigate }) => {
  const activeJobCount = useScrapeStore(
    (s) => s.jobs.filter((j) => j.status === 'running' || j.status === 'pending').length
  )
  return (
    <motion.aside
      initial={{ x: -280 }}
      animate={{ x: 0 }}
      className="w-64 flex flex-col border-r border-glass-border bg-space-800/50 backdrop-blur-xl"
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-glass-border">
        <div className="relative">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-neon-blue to-neon-purple flex items-center justify-center shadow-neon-blue">
            <Youtube className="w-6 h-6 text-white" />
          </div>
          <div className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-neon-green border-2 border-space-800" />
        </div>
        <div>
          <h1 className="font-display font-bold text-lg leading-tight">
            <span className="text-neon-blue">YouTube</span>
            <span className="text-white">Scrape</span>
          </h1>
          <p className="text-xs text-space-300">Professional Edition</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4">
        <ul className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = currentView === item.id

            return (
              <li key={item.id}>
                <button
                  onClick={() => onNavigate(item.id)}
                  className={`
                    w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group
                    ${isActive
                      ? 'bg-gradient-to-r from-neon-blue/20 to-neon-purple/10 border border-neon-blue/30 text-white'
                      : 'text-space-300 hover:bg-white/5 hover:text-white'
                    }
                  `}
                >
                  <Icon className={`w-5 h-5 ${isActive ? 'text-neon-blue' : 'group-hover:text-neon-cyan'}`} />
                  <span className="font-medium text-sm flex-1 text-left truncate">{item.label}</span>
                  {item.id === 'jobs' && activeJobCount > 0 ? (
                    <span
                      className="shrink-0 min-w-[1.35rem] rounded-full bg-neon-cyan px-1.5 py-0.5 text-center text-[11px] font-bold leading-none text-space-900"
                      title={`${activeJobCount} active job${activeJobCount === 1 ? '' : 's'}`}
                    >
                      {activeJobCount > 99 ? '99+' : activeJobCount}
                    </span>
                  ) : null}
                  {isActive && (
                    <motion.div
                      layoutId="activeIndicator"
                      className="shrink-0 w-1.5 h-1.5 rounded-full bg-neon-blue"
                    />
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-glass-border">
        <div className="glass-card p-3 rounded-xl">
          <p className="text-xs text-space-300 mb-2">Quick Tip</p>
          <p className="text-xs text-space-200">
            Press <kbd className="px-1.5 py-0.5 rounded bg-space-700 text-neon-cyan">⌘N</kbd> to start a new scrape
          </p>
        </div>
      </div>
    </motion.aside>
  )
}

export default Sidebar
