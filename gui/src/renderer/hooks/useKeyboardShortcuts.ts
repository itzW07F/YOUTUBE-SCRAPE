import { useEffect, useCallback } from 'react'

interface ShortcutHandlers {
  onNewScrape?: () => void
  onOpenJobs?: () => void
  onOpenResults?: () => void
  onOpenSettings?: () => void
  onOpenDebug?: () => void
  onToggleTheme?: () => void
  onGoBack?: () => void
  onSearch?: () => void
}

export const useKeyboardShortcuts = (handlers: ShortcutHandlers) => {
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0
      const modifier = isMac ? event.metaKey : event.ctrlKey

      // Command/Ctrl + N: New Scrape
      if (modifier && event.key === 'n') {
        event.preventDefault()
        handlers.onNewScrape?.()
      }

      // Command/Ctrl + J: Open Jobs
      if (modifier && event.key === 'j') {
        event.preventDefault()
        handlers.onOpenJobs?.()
      }

      // Command/Ctrl + R: Open Results
      if (modifier && event.key === 'r') {
        event.preventDefault()
        handlers.onOpenResults?.()
      }

      // Command/Ctrl + ,: Open Settings
      if (modifier && event.key === ',') {
        event.preventDefault()
        handlers.onOpenSettings?.()
      }

      // Command/Ctrl + D: Open Debug
      if (modifier && event.key === 'd') {
        event.preventDefault()
        handlers.onOpenDebug?.()
      }

      // Command/Ctrl + Shift + L: Toggle Theme
      if (modifier && event.shiftKey && event.key === 'L') {
        event.preventDefault()
        handlers.onToggleTheme?.()
      }

      // Escape: Go Back
      if (event.key === 'Escape') {
        handlers.onGoBack?.()
      }

      // Command/Ctrl + F: Search
      if (modifier && event.key === 'f') {
        event.preventDefault()
        handlers.onSearch?.()
      }
    },
    [handlers]
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])
}

export default useKeyboardShortcuts
