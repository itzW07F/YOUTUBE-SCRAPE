import React from 'react'
import { motion } from 'framer-motion'
import {
  Play,
  Clock,
  FolderOpen,
  Youtube,
  FileText,
  Image,
  Download,
  Layers,
  ArrowRight,
  Zap,
  MessageSquare,
  HardDrive,
} from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'
import { useDashboardTrackerStore } from '../stores/dashboardTrackerStore'

interface DashboardProps {
  onNavigate: (view: 'scrape' | 'jobs' | 'results') => void
}

function formatStorageBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return '0 B'
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB'] as const
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  const decimals = i === 0 ? 0 : i === 1 ? 0 : v >= 100 ? 0 : 1
  return `${v.toFixed(decimals)} ${units[i]}`
}

const Dashboard: React.FC<DashboardProps> = ({ onNavigate }) => {
  const { jobs, applyScrapePreset } = useScrapeStore()
  const { scrapesStarted, commentsScraped, totalStorageBytes } = useDashboardTrackerStore()

  const recentJobs = jobs.slice(0, 5)

  const statCards = [
    {
      label: 'Total Scrapes',
      display: String(scrapesStarted),
      hint: 'All-time starts',
      icon: Zap,
      iconWrapClass: 'bg-neon-blue/10',
      iconClass: 'text-neon-blue',
    },
    {
      label: 'Comments Scraped',
      display: String(commentsScraped),
      hint: 'All-time comment records',
      icon: MessageSquare,
      iconWrapClass: 'bg-neon-green/10',
      iconClass: 'text-neon-green',
    },
    {
      label: 'Storage Used',
      display: formatStorageBytes(totalStorageBytes),
      hint: 'Configured output folders',
      icon: HardDrive,
      iconWrapClass: 'bg-neon-purple/10',
      iconClass: 'text-neon-purple',
    },
  ]

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card gradient-border p-8"
      >
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-display font-bold mb-2">
              Welcome to <span className="text-neon-blue">YouTube</span>
              <span className="text-neon-purple">Scrape</span>
            </h1>
            <p className="text-space-300 max-w-xl">
              Extract video metadata, comments, transcripts, and download media with our professional scraping toolkit. Fast, reliable, and feature-rich.
            </p>
            <div className="flex gap-3 mt-6">
              <button
                onClick={() => onNavigate('scrape')}
                className="futuristic-btn futuristic-btn-primary flex items-center gap-2"
              >
                <Play className="w-4 h-4" />
                Start New Scrape
              </button>
              <button
                onClick={() => onNavigate('jobs')}
                className="futuristic-btn flex items-center gap-2"
              >
                <Clock className="w-4 h-4" />
                View Jobs
              </button>
            </div>
          </div>
          <div className="w-32 h-32 rounded-2xl bg-gradient-to-br from-neon-blue/20 to-neon-purple/20 flex items-center justify-center">
            <Youtube className="w-16 h-16 text-neon-blue" />
          </div>
        </div>
      </motion.div>

      {/* Stats — persist in userData/dashboard-trackers.json; storage rescanned from disk */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {statCards.map((stat, index) => {
          const Icon = stat.icon
          return (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              className="glass-card p-5 hover:bg-white/[0.07] transition-colors"
            >
              <div className={`w-10 h-10 rounded-xl ${stat.iconWrapClass} flex items-center justify-center mb-3`}>
                <Icon className={`w-5 h-5 ${stat.iconClass}`} />
              </div>
              <p className="text-2xl font-bold text-white tabular-nums">{stat.display}</p>
              <p className="text-sm text-space-400">{stat.label}</p>
              <p className="text-xs text-space-500 mt-1">{stat.hint}</p>
            </motion.div>
          )
        })}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-2 gap-4">
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.4 }}
          className="glass-card p-5"
        >
          <h3 className="font-semibold text-white mb-4">Quick Actions</h3>
          <div className="flex flex-col gap-3">
            <div className="flex justify-center">
              <div className="min-w-0 w-[calc((100%-0.75rem)/2)]">
                <QuickAction
                  icon={Layers}
                  label="Scrape All Data"
                  onClick={() => {
                    applyScrapePreset('all')
                    onNavigate('scrape')
                  }}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <QuickAction
                icon={Youtube}
                label="Scrape Video MetaData"
                onClick={() => {
                  applyScrapePreset('video')
                  onNavigate('scrape')
                }}
              />
              <QuickAction
                icon={FileText}
                label="Scrape Comments/Replies"
                onClick={() => {
                  applyScrapePreset('comments')
                  onNavigate('scrape')
                }}
              />
              <QuickAction
                icon={Image}
                label="Scrape Video Thumbnails"
                onClick={() => {
                  applyScrapePreset('thumbnails')
                  onNavigate('scrape')
                }}
              />
              <QuickAction
                icon={Download}
                label="Scrape Video/Audio"
                onClick={() => {
                  applyScrapePreset('download')
                  onNavigate('scrape')
                }}
              />
            </div>
          </div>
        </motion.div>

        {/* Recent Activity */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.5 }}
          className="glass-card p-5"
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-white">Recent Activity</h3>
            <button
              onClick={() => onNavigate('jobs')}
              className="text-neon-blue text-sm hover:underline flex items-center gap-1"
            >
              View All <ArrowRight className="w-3 h-3" />
            </button>
          </div>
          
          {recentJobs.length === 0 ? (
            <div className="text-center py-8 text-space-400">
              <FolderOpen className="w-10 h-10 mx-auto mb-3 opacity-50" />
              <p>No recent activity</p>
              <p className="text-sm">Start your first scrape to see results here</p>
            </div>
          ) : (
            <div className="space-y-2">
              {recentJobs.map((job) => (
                <div
                  key={job.id}
                  className="flex items-center gap-3 p-3 rounded-lg bg-white/5 hover:bg-white/[0.07] transition-colors"
                >
                  <div className={`w-2 h-2 rounded-full ${
                    job.status === 'completed' ? 'bg-neon-green' :
                    job.status === 'running' ? 'bg-neon-blue animate-pulse' :
                    job.status === 'failed' ? 'bg-rose-500' :
                    'bg-amber-500'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{job.url}</p>
                    <p className="text-xs text-space-400">
                      {job.type} • {job.status}
                    </p>
                  </div>
                  <span className="text-xs text-space-500">
                    {job.progress}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      </div>
    </div>
  )
}

const QuickAction: React.FC<{ icon: React.ElementType; label: string; onClick: () => void }> = ({
  icon: Icon,
  label,
  onClick,
}) => (
  <button
    type="button"
    onClick={onClick}
    className="flex w-full items-center gap-3 rounded-lg border border-transparent bg-white/5 p-3 transition-all hover:bg-white/[0.07] hover:border-neon-blue/30 group"
  >
    <div className="w-8 h-8 rounded-lg bg-neon-blue/10 flex items-center justify-center group-hover:bg-neon-blue/20 transition-colors">
      <Icon className="w-4 h-4 text-neon-blue" />
    </div>
    <span className="text-sm text-space-200 group-hover:text-white transition-colors">{label}</span>
  </button>
)

export default Dashboard
