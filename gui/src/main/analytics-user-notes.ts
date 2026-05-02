import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import type Store from 'electron-store'
import { isOutputDirAllowed } from './media-serve'

/** Stored inside each scrape output folder (alongside video.json, etc.). */
export const ANALYTICS_USER_NOTES_DIR = 'analytics_user_notes'

const MANIFEST_NAME = 'manifest.json'
const MAX_NOTE_BYTES = 4 * 1024 * 1024
const MAX_DISPLAY_NAME_LEN = 120

export interface AnalyticsUserNoteFileMeta {
  id: string
  displayName: string
}

interface ManifestV1 {
  schemaVersion: 1
  files: AnalyticsUserNoteFileMeta[]
}

function notesRoot(outputDir: string): string {
  return path.join(path.resolve(outputDir), ANALYTICS_USER_NOTES_DIR)
}

function manifestPath(outputDir: string): string {
  return path.join(notesRoot(outputDir), MANIFEST_NAME)
}

function bodyPath(outputDir: string, fileId: string): string {
  return path.join(notesRoot(outputDir), `${fileId}.txt`)
}

function assertAllowedFileId(fileId: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(fileId)
}

function validateOutputDir(outputDir: string, store: Store): string | null {
  if (!outputDir || typeof outputDir !== 'string') {
    return 'Invalid folder'
  }
  if (!isOutputDirAllowed(outputDir, store)) {
    return 'Folder is outside allowed output roots'
  }
  return null
}

function readManifest(outputDir: string): ManifestV1 | null {
  const mp = manifestPath(outputDir)
  if (!fs.existsSync(mp)) {
    return null
  }
  try {
    const raw = fs.readFileSync(mp, 'utf8')
    const j = JSON.parse(raw) as unknown
    if (!j || typeof j !== 'object') {
      return null
    }
    const rec = j as Record<string, unknown>
    if (rec.schemaVersion !== 1 || !Array.isArray(rec.files)) {
      return null
    }
    const files: AnalyticsUserNoteFileMeta[] = []
    for (const entry of rec.files) {
      if (!entry || typeof entry !== 'object') {
        continue
      }
      const e = entry as Record<string, unknown>
      if (typeof e.id !== 'string' || typeof e.displayName !== 'string') {
        continue
      }
      if (!assertAllowedFileId(e.id)) {
        continue
      }
      const name = e.displayName.trim().slice(0, MAX_DISPLAY_NAME_LEN) || 'Untitled'
      files.push({ id: e.id, displayName: name })
    }
    return { schemaVersion: 1, files }
  } catch {
    return null
  }
}

function writeManifest(outputDir: string, manifest: ManifestV1): void {
  const root = notesRoot(outputDir)
  fs.mkdirSync(root, { recursive: true })
  fs.writeFileSync(manifestPath(outputDir), JSON.stringify(manifest, null, 2), 'utf8')
}

function ensureDefaultManifest(outputDir: string): ManifestV1 {
  const id = randomUUID()
  const manifest: ManifestV1 = {
    schemaVersion: 1,
    files: [{ id, displayName: 'Notes' }],
  }
  fs.mkdirSync(notesRoot(outputDir), { recursive: true })
  writeManifest(outputDir, manifest)
  fs.writeFileSync(bodyPath(outputDir, id), '', 'utf8')
  return manifest
}

function syncManifestWithDisk(outputDir: string, manifest: ManifestV1): ManifestV1 {
  const existing = manifest.files.filter((f) => fs.existsSync(bodyPath(outputDir, f.id)))
  if (existing.length === manifest.files.length) {
    return manifest
  }
  if (existing.length === 0) {
    return ensureDefaultManifest(outputDir)
  }
  const next: ManifestV1 = { schemaVersion: 1, files: existing }
  writeManifest(outputDir, next)
  return next
}

type NotesOk<T> = { ok: true; data: T }
type NotesErr = { ok: false; error: string }
export type NotesResult<T> = NotesOk<T> | NotesErr

export function listAnalyticsUserNotes(
  outputDir: string,
  store: Store
): NotesResult<{ files: AnalyticsUserNoteFileMeta[] }> {
  const err = validateOutputDir(outputDir, store)
  if (err) {
    return { ok: false, error: err }
  }
  let manifest = readManifest(outputDir)
  if (!manifest || manifest.files.length === 0) {
    manifest = ensureDefaultManifest(outputDir)
  } else {
    manifest = syncManifestWithDisk(outputDir, manifest)
  }
  return { ok: true, data: { files: manifest.files } }
}

export function readAnalyticsUserNote(
  outputDir: string,
  fileId: string,
  store: Store
): NotesResult<{ content: string }> {
  const err = validateOutputDir(outputDir, store)
  if (err) {
    return { ok: false, error: err }
  }
  if (!assertAllowedFileId(fileId)) {
    return { ok: false, error: 'Invalid note id' }
  }
  const bp = bodyPath(outputDir, fileId)
  if (!fs.existsSync(bp)) {
    return { ok: false, error: 'Note file not found' }
  }
  try {
    const stat = fs.statSync(bp)
    if (!stat.isFile() || stat.size > MAX_NOTE_BYTES) {
      return { ok: false, error: 'Note file too large or not a file' }
    }
    const content = fs.readFileSync(bp, 'utf8')
    return { ok: true, data: { content } }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export function writeAnalyticsUserNote(
  outputDir: string,
  fileId: string,
  content: string,
  store: Store
): NotesErr | { ok: true } {
  const err = validateOutputDir(outputDir, store)
  if (err) {
    return { ok: false, error: err }
  }
  if (!assertAllowedFileId(fileId)) {
    return { ok: false, error: 'Invalid note id' }
  }
  if (typeof content !== 'string') {
    return { ok: false, error: 'Invalid content' }
  }
  const bytes = Buffer.byteLength(content, 'utf8')
  if (bytes > MAX_NOTE_BYTES) {
    return { ok: false, error: `Note exceeds ${MAX_NOTE_BYTES} bytes` }
  }
  const manifest = readManifest(outputDir)
  if (!manifest?.files.some((f) => f.id === fileId)) {
    return { ok: false, error: 'Unknown note id' }
  }
  const bp = bodyPath(outputDir, fileId)
  try {
    fs.mkdirSync(notesRoot(outputDir), { recursive: true })
    fs.writeFileSync(bp, content, 'utf8')
    return { ok: true }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export function createAnalyticsUserNote(
  outputDir: string,
  displayName: string | undefined,
  store: Store
): NotesResult<{ file: AnalyticsUserNoteFileMeta }> {
  const err = validateOutputDir(outputDir, store)
  if (err) {
    return { ok: false, error: err }
  }
  let manifest = readManifest(outputDir)
  if (!manifest || manifest.files.length === 0) {
    manifest = ensureDefaultManifest(outputDir)
  } else {
    manifest = syncManifestWithDisk(outputDir, manifest)
  }
  const id = randomUUID()
  const rawName = typeof displayName === 'string' ? displayName.trim() : ''
  const name = (rawName || `Note ${manifest.files.length + 1}`).slice(0, MAX_DISPLAY_NAME_LEN)
  const file: AnalyticsUserNoteFileMeta = { id, displayName: name }
  manifest.files.push(file)
  try {
    writeManifest(outputDir, manifest)
    fs.writeFileSync(bodyPath(outputDir, id), '', 'utf8')
    return { ok: true, data: { file } }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export function deleteAnalyticsUserNote(
  outputDir: string,
  fileId: string,
  store: Store
): NotesResult<{ files: AnalyticsUserNoteFileMeta[] }> {
  const err = validateOutputDir(outputDir, store)
  if (err) {
    return { ok: false, error: err }
  }
  if (!assertAllowedFileId(fileId)) {
    return { ok: false, error: 'Invalid note id' }
  }
  let manifest = readManifest(outputDir)
  if (!manifest || manifest.files.length === 0) {
    manifest = ensureDefaultManifest(outputDir)
  }
  const nextFiles = manifest.files.filter((f) => f.id !== fileId)
  if (nextFiles.length === manifest.files.length) {
    return { ok: false, error: 'Note not found' }
  }
  if (nextFiles.length === 0) {
    return { ok: false, error: 'Cannot delete the last note' }
  }
  const bp = bodyPath(outputDir, fileId)
  try {
    writeManifest(outputDir, { schemaVersion: 1, files: nextFiles })
    if (fs.existsSync(bp)) {
      fs.unlinkSync(bp)
    }
    return { ok: true, data: { files: nextFiles } }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}

export function renameAnalyticsUserNote(
  outputDir: string,
  fileId: string,
  displayName: string,
  store: Store
): NotesResult<{ file: AnalyticsUserNoteFileMeta }> {
  const err = validateOutputDir(outputDir, store)
  if (err) {
    return { ok: false, error: err }
  }
  if (!assertAllowedFileId(fileId)) {
    return { ok: false, error: 'Invalid note id' }
  }
  const name = (typeof displayName === 'string' ? displayName.trim() : '').slice(0, MAX_DISPLAY_NAME_LEN)
  if (!name) {
    return { ok: false, error: 'Name required' }
  }
  let manifest = readManifest(outputDir)
  if (!manifest) {
    return { ok: false, error: 'No manifest' }
  }
  const idx = manifest.files.findIndex((f) => f.id === fileId)
  if (idx < 0) {
    return { ok: false, error: 'Note not found' }
  }
  const file: AnalyticsUserNoteFileMeta = { ...manifest.files[idx], displayName: name }
  const files = [...manifest.files]
  files[idx] = file
  try {
    writeManifest(outputDir, { schemaVersion: 1, files })
    return { ok: true, data: { file } }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) }
  }
}
