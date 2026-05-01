/** Build absolute HTTP URLs for the scrape API (handles stray slashes on ``serverUrl``). */
export function joinServerUrl(base: string | undefined | null, pathname: string): string {
  if (!base) {
    return pathname.startsWith('/') ? pathname : `/${pathname}`
  }
  const root = base.replace(/\/+$/, '')
  const suffix = pathname.startsWith('/') ? pathname : `/${pathname}`
  return `${root}${suffix}`
}
