/** Stable key for matching analytics scrape folders across OS separator differences. */
export function normalizeAnalyticsOutputDirKey(dir: string): string {
  return dir.replace(/[\\/]+$/, '').replace(/\\/g, '/')
}
