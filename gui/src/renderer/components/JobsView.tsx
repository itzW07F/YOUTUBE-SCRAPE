import React, { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Play,
  Pause,
  X,
  FolderOpen,
  Clock,
  CheckCircle,
  AlertCircle,
  Terminal,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { useScrapeStore, ScrapeJob } from '../stores/scrapeStore'
import { useAppStore } from '../stores/appStore'

const JobsView: React.FC = () => {
  const { jobs, activeJobId, setActiveJob, removeJob, updateJob, addJobLog } = useScrapeStore()
  const { serverUrl, isServerRunning } = useAppStore()
  const [expandedJob, setExpandedJob] = useState<string | null>(null)
  const [websockets, setWebsockets] = useState<Map<string, WebSocket>>(new Map())

  // Connect to WebSocket for each running job
  useEffect(() => {
    if (!serverUrl || !isServerRunning) return

    jobs.forEach((job) => {
      if (job.status === 'running' && !websockets.has(job.id)) {
        const ws = new WebSocket(`${serverUrl.replace('http', 'ws')}/ws/progress/${job.id}`)
        
        ws.onmessage = (event) => {
          const data = JSON.parse(event.data)
          
          if (data.progress !== undefined) {
            updateJob(job.id, { progress: data.progress })
          }
          
          if (data.status) {
            const details = data.details || {}
            updateJob(job.id, { 
              status: data.status,
              completedAt: data.status === 'completed' ? new Date().toISOString() : undefined,
              outputDir: typeof details.output_dir === 'string' ? details.output_dir : job.outputDir,
              error: typeof details.error === 'string' ? details.error : job.error,
            })
          }
          
          if (data.log) {
            addJobLog(job.id, {
              level: data.log.level,
              message: data.log.message,
              timestamp: data.log.timestamp || new Date().toISOString()
            })
          }
        }

        ws.onclose = () => {
          setWebsockets((prev) => {
            const next = new Map(prev)
            next.delete(job.id)
            return next
          })
        }

        setWebsockets((prev) => {
          const next = new Map(prev)
          next.set(job.id, ws)
          return next
        })
      }
    })

    // Cleanup WebSockets for completed jobs
    websockets.forEach((ws, jobId) => {
      const job = jobs.find((j) => j.id === jobId)
      if (job && ['completed', 'failed', 'cancelled'].includes(job.status)) {
        ws.close()
      }
    })

    return () => {
      websockets.forEach((ws) => ws.close())
    }
  }, [jobs, serverUrl, isServerRunning])

  const handleCancel = async (jobId: string) => {
    if (!serverUrl) return
    
    try {
      const response = await fetch(`${serverUrl}/jobs/${jobId}/cancel`, { method: 'POST' })
      if (response.ok) {
        updateJob(jobId, { status: 'cancelled' })
      }
    } catch (error) {
      console.error('Failed to cancel job:', error)
    }
  }

  const handleOpenOutput = (outputDir?: string) => {
    if (outputDir) {
      window.electronAPI.openPath(outputDir)
    }
  }

  const sortedJobs = [...jobs].sort((a, b) => {
    const dateA = a.startedAt ? new Date(a.startedAt).getTime() : 0
    const dateB = b.startedAt ? new Date(b.startedAt).getTime() : 0
    return dateB - dateA
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-display font-bold text-white">Job Monitor</h2>
          <p className="text-space-400">Track and manage your scraping jobs</p>
        </div>
        <div className="flex gap-2">
          <span className="px-3 py-1 rounded-full bg-neon-blue/10 text-neon-blue text-sm">
            {jobs.filter((j) => j.status === 'running').length} Running
          </span>
          <span className="px-3 py-1 rounded-full bg-neon-green/10 text-neon-green text-sm">
            {jobs.filter((j) => j.status === 'completed').length} Completed
          </span>
        </div>
      </div>

      {sortedJobs.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <div className="w-20 h-20 rounded-full bg-space-800 flex items-center justify-center mx-auto mb-4">
            <Clock className="w-10 h-10 text-space-400" />
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">No Jobs Yet</h3>
          <p className="text-space-400">Start a new scrape to see jobs here</p>
        </div>
      ) : (
        <div className="space-y-3">
          {sortedJobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              isExpanded={expandedJob === job.id}
              isActive={activeJobId === job.id}
              onToggleExpand={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
              onSetActive={() => setActiveJob(job.id)}
              onCancel={() => handleCancel(job.id)}
              onRemove={() => removeJob(job.id)}
              onOpenOutput={() => handleOpenOutput(job.outputDir)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface JobCardProps {
  job: ScrapeJob
  isExpanded: boolean
  isActive: boolean
  onToggleExpand: () => void
  onSetActive: () => void
  onCancel: () => void
  onRemove: () => void
  onOpenOutput: () => void
}

const JobCard: React.FC<JobCardProps> = ({
  job,
  isExpanded,
  isActive,
  onToggleExpand,
  onSetActive: _onSetActive,
  onCancel,
  onRemove,
  onOpenOutput,
}) => {
  const statusConfig = {
    pending: { color: 'amber', icon: Clock, label: 'Pending' },
    running: { color: 'blue', icon: Play, label: 'Running' },
    completed: { color: 'green', icon: CheckCircle, label: 'Completed' },
    failed: { color: 'rose', icon: AlertCircle, label: 'Failed' },
    cancelled: { color: 'gray', icon: X, label: 'Cancelled' },
  }

  const status = statusConfig[job.status]
  const StatusIcon = status.icon

  return (
    <motion.div
      layout
      className={`
        glass-card overflow-hidden transition-all
        ${isActive ? 'border-neon-blue/40' : ''}
      `}
    >
      <div
        className="p-4 flex items-center gap-4 cursor-pointer"
        onClick={onToggleExpand}
      >
        {/* Status indicator */}
        <div className={`w-10 h-10 rounded-xl bg-${status.color}-500/10 flex items-center justify-center`}>
          <StatusIcon className={`w-5 h-5 text-${status.color}-500`} />
        </div>

        {/* Job info */}
        <div className="flex-1 min-w-0">
          <p className="text-white font-medium truncate">{job.url}</p>
          <div className="flex items-center gap-3 text-sm text-space-400">
            <span>{job.type}</span>
            <span>•</span>
            <span>{status.label}</span>
            {job.startedAt && (
              <>
                <span>•</span>
                <span>{new Date(job.startedAt).toLocaleString()}</span>
              </>
            )}
          </div>
        </div>

        {/* Progress */}
        {job.status === 'running' && (
          <div className="w-32">
            <div className="flex items-center justify-between text-sm mb-1">
              <span className="text-space-400">Progress</span>
              <span className="text-white">{job.progress}%</span>
            </div>
            <div className="progress-bar h-2">
              <div
                className="progress-bar-fill h-full"
                style={{ width: `${job.progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2">
          {job.status === 'running' && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onCancel()
              }}
              className="p-2 rounded-lg hover:bg-rose-500/10 text-space-400 hover:text-rose-400 transition-colors"
              title="Cancel job"
            >
              <Pause className="w-4 h-4" />
            </button>
          )}
          
          {job.outputDir && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onOpenOutput()
              }}
              className="p-2 rounded-lg hover:bg-white/10 text-space-400 hover:text-white transition-colors"
              title="Open output folder"
            >
              <FolderOpen className="w-4 h-4" />
            </button>
          )}
          
          <button
            onClick={(e) => {
              e.stopPropagation()
              onRemove()
            }}
            className="p-2 rounded-lg hover:bg-rose-500/10 text-space-400 hover:text-rose-400 transition-colors"
            title="Remove job"
          >
            <X className="w-4 h-4" />
          </button>

          <button className="p-2 text-space-400">
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Expanded details */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-glass-border"
          >
            <div className="p-4 space-y-4">
              {/* Job details */}
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-space-400 mb-1">Job ID</p>
                  <p className="text-white font-mono">{job.id}</p>
                </div>
                <div>
                  <p className="text-space-400 mb-1">Output Directory</p>
                  <p className="text-white font-mono truncate">{job.outputDir || 'N/A'}</p>
                </div>
                <div>
                  <p className="text-space-400 mb-1">Progress</p>
                  <p className="text-white">{job.progress}%</p>
                </div>
              </div>

              {/* Logs */}
              {job.logs.length > 0 && (
                <div>
                  <p className="text-sm text-space-400 mb-2 flex items-center gap-2">
                    <Terminal className="w-4 h-4" />
                    Logs ({job.logs.length} entries)
                  </p>
                  <div className="code-block p-3 max-h-48 overflow-auto space-y-1">
                    {job.logs.map((log, index) => (
                      <div key={index} className="flex gap-2 text-xs">
                        <span className="text-space-500">
                          {new Date(log.timestamp).toLocaleTimeString()}
                        </span>
                        <span className={`
                          font-medium uppercase
                          ${log.level === 'error' ? 'text-rose-400' :
                            log.level === 'warn' ? 'text-amber-400' :
                            log.level === 'info' ? 'text-neon-blue' : 'text-space-400'}
                        `}>
                          {log.level}
                        </span>
                        <span className="text-space-300">{log.message}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export default JobsView
