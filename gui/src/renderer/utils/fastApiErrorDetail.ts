/** FastAPI commonly returns `{ "detail": "..." | [...] }` JSON for HTTP errors. */

export function extractFastApiErrorDetail(bodyText: string): string | null {
  const t = bodyText.trim()
  if (!t.startsWith('{') && !t.startsWith('[')) {
    return null
  }
  try {
    const o = JSON.parse(t) as { detail?: unknown }
    const d = o.detail
    if (typeof d === 'string') {
      return d
    }
    if (Array.isArray(d)) {
      return JSON.stringify(d)
    }
    if (d && typeof d === 'object') {
      return JSON.stringify(d)
    }
    return null
  } catch {
    return null
  }
}
