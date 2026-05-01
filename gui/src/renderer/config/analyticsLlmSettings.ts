/** electron-store keys + defaults for analytics LLM (must match `youtubeScrapeSpawnEnvExtras` in main). */

export type AnalyticsLlmProviderId = 'ollama' | 'openai_compatible' | 'anthropic' | 'google_gemini'

export const ANALYTICS_LLM_PROVIDER_OPTIONS: { id: AnalyticsLlmProviderId; label: string }[] = [
  { id: 'ollama', label: 'Ollama' },
  { id: 'openai_compatible', label: 'OpenAI-compatible API' },
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'google_gemini', label: 'Google Gemini' },
]

export const ANALYTICS_LLM_STORE_DEFAULTS: {
  analyticsLlmProvider: AnalyticsLlmProviderId
  analyticsOllamaEnabled: boolean
  ollamaBaseUrl: string
  ollamaModel: string
  openaiCompatibleBaseUrl: string
  openaiCompatibleApiKey: string
  openaiCompatibleModel: string
  anthropicBaseUrl: string
  anthropicApiKey: string
  anthropicModel: string
  googleGeminiApiKey: string
  googleGeminiModel: string
} = {
  analyticsLlmProvider: 'ollama',
  analyticsOllamaEnabled: true,
  ollamaBaseUrl: 'http://127.0.0.1:11434',
  ollamaModel: 'gpt-oss:20b',
  openaiCompatibleBaseUrl: 'https://api.openai.com/v1',
  openaiCompatibleApiKey: '',
  openaiCompatibleModel: 'gpt-4o-mini',
  anthropicBaseUrl: 'https://api.anthropic.com',
  anthropicApiKey: '',
  anthropicModel: 'claude-sonnet-4-20250514',
  googleGeminiApiKey: '',
  googleGeminiModel: 'gemini-2.0-flash',
}
