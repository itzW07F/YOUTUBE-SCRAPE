import {
  ANALYTICS_LLM_PROVIDER_OPTIONS,
  ANALYTICS_LLM_STORE_DEFAULTS,
  type AnalyticsLlmProviderId,
} from '../config/analyticsLlmSettings'

function stripTrailingSlashes(s: string): string {
  const t = s.trim()
  if (!t) {
    return t
  }
  return t.replace(/\/+$/, '')
}

function providerFromUnknown(raw: unknown): AnalyticsLlmProviderId {
  const s = typeof raw === 'string' ? raw : ''
  return ANALYTICS_LLM_PROVIDER_OPTIONS.some((x) => x.id === s) ? (s as AnalyticsLlmProviderId) : 'ollama'
}

function stringOrDefault(raw: unknown, fallback: string): string {
  if (typeof raw === 'string') {
    return raw.trim() || fallback
  }
  return fallback
}

function boolOrDefault(raw: unknown, fallback: boolean): boolean {
  if (raw === false) {
    return false
  }
  if (raw === true) {
    return true
  }
  return fallback
}

/** Full GUI snapshot merged into Python Settings for Analytics LLM (snake_case = Pydantic field names). */
export type GuiAnalyticsLlmOverlaySnakeCase = Record<string, string | boolean>

/** Persist current Settings form state to electron-store (same mapping as spawn env extras). */
export async function persistAnalyticsLlmUiToStore(fields: {
  llmProvider: AnalyticsLlmProviderId
  analyticsLlmEnabled: boolean
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
}): Promise<void> {
  if (!window.electronAPI) {
    return
  }
  await window.electronAPI.storeSet('analyticsLlmProvider', fields.llmProvider)
  await window.electronAPI.storeSet('analyticsOllamaEnabled', fields.analyticsLlmEnabled)
  await window.electronAPI.storeSet('ollamaBaseUrl', fields.ollamaBaseUrl.trim())
  await window.electronAPI.storeSet('ollamaModel', fields.ollamaModel.trim())
  await window.electronAPI.storeSet('openaiCompatibleBaseUrl', fields.openaiCompatibleBaseUrl.trim())
  await window.electronAPI.storeSet('openaiCompatibleApiKey', fields.openaiCompatibleApiKey)
  await window.electronAPI.storeSet('openaiCompatibleModel', fields.openaiCompatibleModel.trim())
  await window.electronAPI.storeSet('anthropicBaseUrl', fields.anthropicBaseUrl.trim())
  await window.electronAPI.storeSet('anthropicApiKey', fields.anthropicApiKey)
  await window.electronAPI.storeSet('anthropicModel', fields.anthropicModel.trim())
  await window.electronAPI.storeSet('googleGeminiApiKey', fields.googleGeminiApiKey)
  await window.electronAPI.storeSet('googleGeminiModel', fields.googleGeminiModel.trim())
}

/** Builds the overlay Python merges on each analytics LLM API call so remote URLs work without restarting the API. */
export async function readGuiAnalyticsLlmOverlay(): Promise<GuiAnalyticsLlmOverlaySnakeCase | undefined> {
  if (typeof window === 'undefined' || !window.electronAPI) {
    return undefined
  }
  const d = ANALYTICS_LLM_STORE_DEFAULTS
  const [
    analyticsLlmProvider,
    analyticsOllamaEnabled,
    ollamaBaseUrl,
    ollamaModel,
    openaiCompatibleBaseUrl,
    openaiCompatibleApiKey,
    openaiCompatibleModel,
    anthropicBaseUrl,
    anthropicApiKey,
    anthropicModel,
    googleGeminiApiKey,
    googleGeminiModel,
  ] = await Promise.all([
    window.electronAPI.storeGet('analyticsLlmProvider'),
    window.electronAPI.storeGet('analyticsOllamaEnabled'),
    window.electronAPI.storeGet('ollamaBaseUrl'),
    window.electronAPI.storeGet('ollamaModel'),
    window.electronAPI.storeGet('openaiCompatibleBaseUrl'),
    window.electronAPI.storeGet('openaiCompatibleApiKey'),
    window.electronAPI.storeGet('openaiCompatibleModel'),
    window.electronAPI.storeGet('anthropicBaseUrl'),
    window.electronAPI.storeGet('anthropicApiKey'),
    window.electronAPI.storeGet('anthropicModel'),
    window.electronAPI.storeGet('googleGeminiApiKey'),
    window.electronAPI.storeGet('googleGeminiModel'),
  ])

  return {
    analytics_llm_provider: providerFromUnknown(analyticsLlmProvider),
    analytics_ollama_enabled: boolOrDefault(analyticsOllamaEnabled, d.analyticsOllamaEnabled),
    ollama_base_url: stripTrailingSlashes(stringOrDefault(ollamaBaseUrl, d.ollamaBaseUrl)),
    ollama_model: stringOrDefault(ollamaModel, d.ollamaModel),
    openai_compatible_base_url: stripTrailingSlashes(
      stringOrDefault(openaiCompatibleBaseUrl, d.openaiCompatibleBaseUrl)
    ),
    openai_compatible_api_key: stringOrDefault(openaiCompatibleApiKey, d.openaiCompatibleApiKey),
    openai_compatible_model: stringOrDefault(openaiCompatibleModel, d.openaiCompatibleModel),
    anthropic_base_url: stripTrailingSlashes(stringOrDefault(anthropicBaseUrl, d.anthropicBaseUrl)),
    anthropic_api_key: stringOrDefault(anthropicApiKey, d.anthropicApiKey),
    anthropic_model: stringOrDefault(anthropicModel, d.anthropicModel),
    google_gemini_api_key: stringOrDefault(googleGeminiApiKey, d.googleGeminiApiKey),
    google_gemini_model: stringOrDefault(googleGeminiModel, d.googleGeminiModel),
  }
}
