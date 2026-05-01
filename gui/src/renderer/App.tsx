import React, { useCallback, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Toaster } from 'react-hot-toast'
import Sidebar from './components/Sidebar'
import Dashboard from './components/Dashboard'
import ScrapeView from './components/ScrapeView'
import JobsView from './components/JobsView'
import ResultsView from './components/ResultsView'
import VideoGalleryView from './components/VideoGalleryView'
import { GalleryFloatingPlayer } from './components/GalleryFloatingPlayer'
import SettingsView from './components/SettingsView'
import DebugView from './components/DebugView'
import AnalyticsView from './components/AnalyticsView'
import Header from './components/Header'
import ServerStatusBar from './components/ServerStatusBar'
import {
  useAppStore,
  hydrateDownloadSpawnSettingsFromStore,
  hydrateOutputDirectoryFromStore,
  hydrateThemeFromStore,
  hydrateUiFontSizeFromStore,
} from './stores/appStore'
import {
  hydrateScrapeJobsFromStore,
  useScrapeStore,
  jobsForPersistence,
  scrapePersistenceReady,
  persistScrapeJobsNow,
} from './stores/scrapeStore'
import { useDashboardTrackerStore } from './stores/dashboardTrackerStore'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'

type View = 'dashboard' | 'scrape' | 'jobs' | 'results' | 'gallery' | 'analytics' | 'settings' | 'debug'

type NavigateOptions = { preserveScrapeOptions?: boolean }

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>('dashboard')
  const { isServerRunning, checkServerStatus, isDarkMode, setDarkMode } = useAppStore()

  const navigate = useCallback((view: View, options?: NavigateOptions) => {
    if (view === 'scrape' && !options?.preserveScrapeOptions) {
      useScrapeStore.getState().resetScrapeTogglesToNone()
    }
    setCurrentView(view)
  }, [])

  // Setup keyboard shortcuts
  useKeyboardShortcuts({
    onNewScrape: () => navigate('scrape'),
    onOpenJobs: () => navigate('jobs'),
    onOpenResults: () => navigate('results'),
    onOpenSettings: () => navigate('settings'),
    onOpenDebug: () => navigate('debug'),
    onToggleTheme: () => setDarkMode(!isDarkMode),
    onGoBack: () => navigate('dashboard'),
  })

  useEffect(() => {
    hydrateOutputDirectoryFromStore()
    hydrateThemeFromStore()
    hydrateUiFontSizeFromStore()
    hydrateDownloadSpawnSettingsFromStore()
    hydrateScrapeJobsFromStore()
    void useDashboardTrackerStore.getState().hydrate()
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined' || !window.electronAPI?.onDashboardTrackersUpdated) {
      return
    }
    return window.electronAPI.onDashboardTrackersUpdated((payload) => {
      useDashboardTrackerStore.getState().replaceFromMain(payload)
    })
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined' || !window.electronAPI) {
      return
    }
    const api = window.electronAPI
    let t: number
    const unsub = useScrapeStore.subscribe((s) => {
      if (!scrapePersistenceReady) {
        return
      }
      window.clearTimeout(t)
      t = window.setTimeout(() => {
        void api.storeSet('scrapeJobs', jobsForPersistence(s.jobs))
      }, 150)
    })
    return () => {
      window.clearTimeout(t)
      unsub()
    }
  }, [])

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        persistScrapeJobsNow()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  useEffect(() => {
    // Check server status on mount
    checkServerStatus()
    
    // Poll server status every 5 seconds
    const interval = setInterval(checkServerStatus, 5000)
    return () => clearInterval(interval)
  }, [checkServerStatus])

  const renderView = () => {
    switch (currentView) {
      case 'dashboard':
        return <Dashboard onNavigate={navigate} />
      case 'scrape':
        return <ScrapeView onNavigate={navigate} />
      case 'jobs':
        return <JobsView />
      case 'results':
        return <ResultsView />
      case 'gallery':
        return <VideoGalleryView onNavigateToJobs={() => navigate('jobs')} />
      case 'analytics':
        return <AnalyticsView onNavigateToGallery={() => navigate('gallery')} />
      case 'settings':
        return <SettingsView />
      case 'debug':
        return <DebugView />
      default:
        return <Dashboard onNavigate={navigate} />
    }
  }

  return (
    <div
      className={
        isDarkMode
          ? 'app-shell flex h-screen w-screen overflow-hidden bg-space-900 text-white'
          : 'app-shell light-mode flex h-screen w-screen overflow-hidden bg-zinc-100 text-zinc-900'
      }
    >
      <Toaster
        position="bottom-right"
        containerStyle={{ zIndex: 2147483647 }}
        toastOptions={{
          duration: 4000,
          style: isDarkMode
            ? {
                background: 'rgba(26, 26, 46, 0.95)',
                color: '#fff',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                backdropFilter: 'blur(10px)',
              }
            : {
                background: 'rgba(255, 255, 255, 0.95)',
                color: '#18181b',
                border: '1px solid rgba(0, 0, 0, 0.08)',
                backdropFilter: 'blur(10px)',
              },
          success: {
            iconTheme: {
              primary: '#f59e0b',
              secondary: '#fff',
            },
          },
          error: {
            iconTheme: {
              primary: '#f43f5e',
              secondary: '#fff',
            },
          },
        }}
      />
      
      <Sidebar currentView={currentView} onNavigate={navigate} />
      
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header currentView={currentView} />
        
        <main className="flex-1 overflow-auto p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentView}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.3 }}
              className="h-full"
            >
              {renderView()}
            </motion.div>
          </AnimatePresence>
        </main>
        
        <GalleryFloatingPlayer currentView={currentView} />
        <ServerStatusBar isRunning={isServerRunning} />
      </div>
    </div>
  )
}

export default App
