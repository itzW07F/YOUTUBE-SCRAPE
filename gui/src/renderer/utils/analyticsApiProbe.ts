import { joinServerUrl } from './joinServerUrl'

/** Whether OpenAPI lists ``POST pathKey`` (e.g. ``/analytics/snapshot``); ``null`` if unreadable. */
export async function openapiHasPostPath(serverUrl: string, pathKey: string): Promise<boolean | null> {
  try {
    const res = await fetch(joinServerUrl(serverUrl, '/openapi.json'))
    if (!res.ok) {
      return null
    }
    const doc: unknown = await res.json()
    if (!doc || typeof doc !== 'object' || !('paths' in doc)) {
      return null
    }
    const paths = (doc as { paths?: Record<string, unknown> }).paths
    if (!paths || typeof paths !== 'object') {
      return null
    }
    const entry = paths[pathKey]
    if (!entry || typeof entry !== 'object') {
      return false
    }
    return Object.prototype.hasOwnProperty.call(entry, 'post')
  } catch {
    return null
  }
}
