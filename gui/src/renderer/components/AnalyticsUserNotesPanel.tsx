import React, { useCallback, useEffect, useRef, useState } from 'react'
import { FilePlus, Loader2, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

const SAVE_DEBOUNCE_MS = 450

type NoteFile = { id: string; displayName: string }

async function flushPendingSave(
  api: NonNullable<typeof window.electronAPI>,
  outputDir: string,
  fileId: string,
  text: string,
  lastSaved: string
): Promise<{ ok: boolean; error?: string }> {
  if (text === lastSaved) {
    return { ok: true }
  }
  const r = await api.analyticsNotesWrite(outputDir, fileId, text)
  if (!r.ok) {
    return { ok: false, error: r.error }
  }
  return { ok: true }
}

export const AnalyticsUserNotesPanel: React.FC<{
  outputDir: string
  /** Omit outer card + title when wrapped by e.g. CollapsibleSection. */
  variant?: 'standalone' | 'embedded'
}> = ({ outputDir, variant = 'standalone' }) => {
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined
  const [files, setFiles] = useState<NoteFile[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const activeIdRef = useRef<string | null>(null)
  const draftRef = useRef('')
  const lastSavedRef = useRef('')

  activeIdRef.current = activeId
  draftRef.current = draft

  const clearDebounce = useCallback(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
  }, [])

  const doSaveNow = useCallback(
    async (fileId: string | null, text: string): Promise<boolean> => {
      if (!api?.analyticsNotesWrite || !fileId || !outputDir) {
        return false
      }
      const prev = lastSavedRef.current
      const r = await flushPendingSave(api, outputDir, fileId, text, prev)
      if (!r.ok) {
        setSaveState('error')
        toast.error(r.error ?? 'Could not save notes')
        return false
      }
      lastSavedRef.current = text
      setSaveState('saved')
      window.setTimeout(() => setSaveState((s) => (s === 'saved' ? 'idle' : s)), 1600)
      return true
    },
    [api, outputDir]
  )

  const scheduleSave = useCallback(() => {
    clearDebounce()
    const fid = activeIdRef.current
    if (!fid) {
      return
    }
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null
      void (async () => {
        setSaveState('saving')
        await doSaveNow(fid, draftRef.current)
      })()
    }, SAVE_DEBOUNCE_MS)
  }, [clearDebounce, doSaveNow])

  const loadFiles = useCallback(async () => {
    if (!api?.analyticsNotesList || !outputDir) {
      setFiles([])
      setActiveId(null)
      setDraft('')
      lastSavedRef.current = ''
      setLoading(false)
      return
    }
    setLoading(true)
    const listR = await api.analyticsNotesList(outputDir)
    if (!listR.ok) {
      toast.error(listR.error)
      setFiles([])
      setActiveId(null)
      setDraft('')
      lastSavedRef.current = ''
      setLoading(false)
      return
    }
    setFiles(listR.files)
    const firstId = listR.files[0]?.id ?? null
    setActiveId((prev) => (prev && listR.files.some((f) => f.id === prev) ? prev : firstId))
    setLoading(false)
  }, [api, outputDir])

  useEffect(() => {
    void loadFiles()
  }, [loadFiles])

  useEffect(() => {
    if (!api?.analyticsNotesRead || !outputDir || !activeId) {
      return
    }
    let cancelled = false
    void (async () => {
      clearDebounce()
      const readR = await api.analyticsNotesRead(outputDir, activeId)
      if (cancelled) {
        return
      }
      if (!readR.ok) {
        toast.error(readR.error)
        setDraft('')
        lastSavedRef.current = ''
        return
      }
      setDraft(readR.content)
      lastSavedRef.current = readR.content
      setSaveState('idle')
    })()
    return () => {
      cancelled = true
    }
  }, [api, outputDir, activeId, clearDebounce])

  useEffect(() => {
    return () => {
      clearDebounce()
    }
  }, [clearDebounce])

  const onBlurEditor = useCallback(() => {
    clearDebounce()
    const fid = activeIdRef.current
    if (!fid) {
      return
    }
    void (async () => {
      setSaveState('saving')
      await doSaveNow(fid, draftRef.current)
    })()
  }, [clearDebounce, doSaveNow])

  const selectFile = useCallback(
    async (nextId: string) => {
      if (nextId === activeIdRef.current) {
        return
      }
      clearDebounce()
      const prevId = activeIdRef.current
      const text = draftRef.current
      if (prevId && api?.analyticsNotesWrite) {
        setSaveState('saving')
        const r = await flushPendingSave(api, outputDir, prevId, text, lastSavedRef.current)
        if (!r.ok) {
          toast.error(r.error ?? 'Save failed — switch cancelled')
          setSaveState('error')
          return
        }
        lastSavedRef.current = text
      }
      setActiveId(nextId)
    },
    [api, clearDebounce, outputDir]
  )

  const onAddFile = useCallback(async () => {
    if (!api?.analyticsNotesCreate || !outputDir) {
      return
    }
    clearDebounce()
    const prevId = activeIdRef.current
    if (prevId) {
      setSaveState('saving')
      const saved = await doSaveNow(prevId, draftRef.current)
      if (!saved) {
        return
      }
    }
    const r = await api.analyticsNotesCreate(outputDir)
    if (!r.ok) {
      toast.error(r.error)
      return
    }
    setFiles((prev) => [...prev, r.file])
    lastSavedRef.current = ''
    setDraft('')
    setActiveId(r.file.id)
    setSaveState('idle')
  }, [api, clearDebounce, doSaveNow, outputDir])

  const onDeleteFile = useCallback(
    async (fileId: string) => {
      if (!api?.analyticsNotesDelete || !outputDir) {
        return
      }
      if (!window.confirm('Remove this note file? Its text will be deleted from disk.')) {
        return
      }
      clearDebounce()
      const r = await api.analyticsNotesDelete(outputDir, fileId)
      if (!r.ok) {
        toast.error(r.error)
        return
      }
      setFiles(r.files)
      if (activeIdRef.current === fileId) {
        const next = r.files[0]?.id ?? null
        setActiveId(next)
        if (!next) {
          setDraft('')
          lastSavedRef.current = ''
        }
      }
    },
    [api, clearDebounce, outputDir]
  )

  const commitRename = useCallback(async () => {
    if (!renamingId || !api?.analyticsNotesRename || !outputDir) {
      setRenamingId(null)
      return
    }
    const r = await api.analyticsNotesRename(outputDir, renamingId, renameDraft)
    setRenamingId(null)
    if (!r.ok) {
      toast.error(r.error)
      return
    }
    setFiles((prev) => prev.map((f) => (f.id === r.file.id ? r.file : f)))
  }, [api, outputDir, renameDraft, renamingId])

  if (!api?.analyticsNotesList) {
    return (
      <div
        className={
          variant === 'embedded'
            ? 'p-5 text-sm text-space-500'
            : 'glass-card overflow-hidden border border-white/10 p-5 text-sm text-space-500'
        }
      >
        Notes require the desktop app (Electron preload).
      </div>
    )
  }

  const editor = (
    <div className="flex min-h-[280px] flex-col gap-0 md:flex-row md:items-start">
        <aside className="flex w-full shrink-0 flex-col border-b border-white/10 md:w-52 md:border-b-0 md:border-r md:border-white/10">
          <div className="flex items-center justify-between gap-2 border-b border-white/5 p-2">
            <span className="px-2 text-xs font-medium uppercase tracking-wide text-space-500">Files</span>
            <button
              type="button"
              onClick={() => void onAddFile()}
              className="futuristic-btn flex items-center gap-1 px-2 py-1 text-xs"
              title="New note file"
            >
              <FilePlus className="h-3.5 w-3.5" />
              Add
            </button>
          </div>
          <div className="max-h-64 flex-1 overflow-y-auto p-2 md:max-h-none">
            {loading ? (
              <div className="flex items-center justify-center py-8 text-space-500">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : files.length === 0 ? (
              <p className="px-2 py-4 text-xs text-space-500">No note files yet.</p>
            ) : (
              <ul className="space-y-1">
                {files.map((f) => {
                  const active = f.id === activeId
                  return (
                    <li key={f.id}>
                      <div
                        className={`flex items-center gap-1 rounded-md border px-1 py-0.5 ${
                          active ? 'border-neon-purple/50 bg-neon-purple/10' : 'border-transparent hover:bg-white/5'
                        }`}
                      >
                        {renamingId === f.id ? (
                          <input
                            autoFocus
                            value={renameDraft}
                            onChange={(e) => setRenameDraft(e.target.value)}
                            onBlur={() => void commitRename()}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault()
                                void commitRename()
                              }
                              if (e.key === 'Escape') {
                                setRenamingId(null)
                              }
                            }}
                            className="futuristic-input min-w-0 flex-1 py-0.5 text-xs"
                          />
                        ) : (
                          <button
                            type="button"
                            onClick={() => void selectFile(f.id)}
                            className="min-w-0 flex-1 truncate px-1 py-1 text-left text-sm text-space-200"
                            title="Open note"
                          >
                            <span
                              className="block truncate"
                              onDoubleClick={(ev) => {
                                ev.stopPropagation()
                                ev.preventDefault()
                                setRenamingId(f.id)
                                setRenameDraft(f.displayName)
                              }}
                            >
                              {f.displayName}
                            </span>
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => void onDeleteFile(f.id)}
                          disabled={files.length <= 1}
                          className="shrink-0 rounded p-1 text-space-500 hover:bg-rose-500/15 hover:text-rose-300 disabled:opacity-30"
                          title={files.length <= 1 ? 'Cannot delete last note' : 'Delete note'}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </aside>
        <div className="flex min-h-[220px] w-full min-w-0 flex-1 flex-col p-3 md:min-h-0">
          <div className="mb-2 flex min-h-[1.25rem] items-center justify-end text-xs text-space-500">
            {saveState === 'saving' ? (
              <span className="flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" /> Saving…
              </span>
            ) : saveState === 'saved' ? (
              <span className="text-neon-green/90">Saved</span>
            ) : saveState === 'error' ? (
              <span className="text-rose-300">Save failed</span>
            ) : (
              <span>Double-click a name to rename</span>
            )}
          </div>
          <textarea
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              setSaveState('idle')
              scheduleSave()
            }}
            onBlur={() => onBlurEditor()}
            disabled={!activeId || loading}
            placeholder={activeId ? 'Type notes… (saved automatically)' : 'Pick or create a note file'}
            className="futuristic-input box-border min-h-[200px] w-full max-w-full shrink-0 resize-y font-mono text-sm leading-relaxed"
            spellCheck
          />
        </div>
      </div>
  )

  if (variant === 'embedded') {
    return editor
  }

  return (
    <div className="glass-card overflow-visible border border-white/10">
      <div className="border-b border-white/10 px-5 py-3">
        <h3 className="text-lg font-semibold text-white">Your notes</h3>
        <p className="mt-0.5 text-xs text-space-500">
          Auto-saved to <span className="font-mono text-space-400">analytics_user_notes</span> in this scrape folder
          (plain text per file + manifest).
        </p>
      </div>
      {editor}
    </div>
  )
}
