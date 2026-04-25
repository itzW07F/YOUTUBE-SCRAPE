import React, { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Toaster } from 'react-hot-toast'
import Sidebar from './components/Sidebar'
import Dashboard from './components/Dashboard'
import ScrapeView from './components/ScrapeView'
import JobsView from './components/JobsView'
import ResultsView from './components/ResultsView'
import VideoGalleryView from './components/VideoGalleryView'
import SettingsView from './components/SettingsView'
import DebugView from './components/DebugView'
import Header from './components/Header'
import ServerStatusBar from './components/ServerStatusBar'
import {
  useAppStore,
  hydrateOutputDirectoryFromStore,
  hydrateThemeFromStore,
  hydrateUiFontSizeFromStore,
} from './stores/appStore'
import {
  hydrateScrapeJobsFromStore,
  useScrapeStore,
  jobsForPersistence,
  scrapePersistenceReady,
} from './stores/scrapeStore'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'

type View = 'dashboard' | 'scrape' | 'jobs' | 'results' | 'gallery' | 'settings' | 'debug'

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>('dashboard')
  const { isServerRunning, checkServerStatus, isDarkMode, setDarkMode } = useAppStore()

  // Setup keyboard shortcuts
  useKeyboardShortcuts({
    onNewScrape: () => setCurrentView('scrape'),
    onOpenJobs: () => setCurrentView('jobs'),
    onOpenResults: () => setCurrentView('results'),
    onOpenSettings: () => setCurrentView('settings'),
    onOpenDebug: () => setCurrentView('debug'),
    onToggleTheme: () => setDarkMode(!isDarkMode),
    onGoBack: () => setCurrentView('dashboard'),
  })

  useEffect(() => {
    hydrateOutputDirectoryFromStore()
    hydrateThemeFromStore()
    hydrateUiFontSizeFromStore()
    hydrateScrapeJobsFromStore()
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
      }, 400)
    })
    return () => {
      window.clearTimeout(t)
      unsub()
    }
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
        return <Dashboard onNavigate={setCurrentView} />
      case 'scrape':
        return <ScrapeView onNavigate={setCurrentView} />
      case 'jobs':
        return <JobsView />
      case 'results':
        return <ResultsView />
      case 'gallery':
        return <VideoGalleryView />
      case 'settings':
        return <SettingsView />
      case 'debug':
        return <DebugView />
      default:
        return <Dashboard onNavigate={setCurrentView} />
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
              primary: '#10b981',
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
      
      <Sidebar currentView={currentView} onNavigate={setCurrentView} />
      
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
        
        <ServerStatusBar isRunning={isServerRunning} />
      </div>
    </div>
  )
}

export default App
