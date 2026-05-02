/** Synthetic job IDs (no `/ws/progress`); UI tracks completion in the initiating view. */
export const GALLERY_METADATA_JOB_PREFIX = 'gallery-metadata-'
export const ANALYTICS_METADATA_JOB_PREFIX = 'analytics-metadata-'

export function jobIdUsesProgressWebSocket(jobId: string): boolean {
  return (
    !jobId.startsWith(GALLERY_METADATA_JOB_PREFIX) &&
    !jobId.startsWith(ANALYTICS_METADATA_JOB_PREFIX)
  )
}
