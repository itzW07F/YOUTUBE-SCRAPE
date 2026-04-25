import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  Play,
  Clock,
  FolderOpen,
  CheckCircle,
  Youtube,
  FileText,
  Image,
  Download,
  ArrowRight,
  Zap,
  TrendingUp,
} from 'lucide-react'
import { useScrapeStore } from '../stores/scrapeStore'

interface DashboardProps {
  onNavigate: (view: 'scrape' | 'jobs' | 'results') => void
}

const Dashboard: React.FC<DashboardProps> = ({ onNavigate }) => {
  const { jobs } = useScrapeStore()
  const [stats, setStats] = useState({
    totalJobs: 0,
    completedJobs: 0,
    pendingJobs: 0,
    failedJobs: 0,
  })

  useEffect(() => {
    setStats({
      totalJobs: jobs.length,
      completedJobs: jobs.filter((j) => j.status === 'completed').length,
      pendingJobs: jobs.filter((j) => j.status === 'pending' || j.status === 'running').length,
      failedJobs: jobs.filter((j) => j.status === 'failed').length,
    })
  }, [jobs])

  const recentJobs = jobs.slice(0, 5)

  const statCards = [
    { label: 'Total Scrapes', value: stats.totalJobs, icon: Zap, color: 'neon-blue' },
    { label: 'Completed', value: stats.completedJobs, icon: CheckCircle, color: 'neon-green' },
    { label: 'Pending', value: stats.pendingJobs, icon: Clock, color: 'amber-500' },
    { label: 'Failed', value: stats.failedJobs, icon: TrendingUp, color: 'rose-500' },
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

      {/* Stats Grid */}
      <div className="grid grid-cols-4 gap-4">
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
              <div className={`w-10 h-10 rounded-xl bg-${stat.color}/10 flex items-center justify-center mb-3`}>
                <Icon className={`w-5 h-5 text-${stat.color}`} />
              </div>
              <p className="text-2xl font-bold text-white">{stat.value}</p>
              <p className="text-sm text-space-400">{stat.label}</p>
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
          <div className="grid grid-cols-2 gap-3">
            <QuickAction icon={Youtube} label="Scrape Video" onClick={() => onNavigate('scrape')} />
            <QuickAction icon={FileText} label="Comments" onClick={() => onNavigate('scrape')} />
            <QuickAction icon={Image} label="Thumbnails" onClick={() => onNavigate('scrape')} />
            <QuickAction icon={Download} label="Download" onClick={() => onNavigate('scrape')} />
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
    onClick={onClick}
    className="flex items-center gap-3 p-3 rounded-lg bg-white/5 hover:bg-white/[0.07] hover:border-neon-blue/30 border border-transparent transition-all group"
  >
    <div className="w-8 h-8 rounded-lg bg-neon-blue/10 flex items-center justify-center group-hover:bg-neon-blue/20 transition-colors">
      <Icon className="w-4 h-4 text-neon-blue" />
    </div>
    <span className="text-sm text-space-200 group-hover:text-white transition-colors">{label}</span>
  </button>
)

export default Dashboard
