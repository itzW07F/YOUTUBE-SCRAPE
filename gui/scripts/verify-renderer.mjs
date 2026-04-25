/**
 * Assumes Vite is already serving http://127.0.0.1:5173/ (e.g. from verify-gui.sh + npm run dev).
 * Writes ../verify-screenshot.png relative to this script.
 */
import { chromium } from 'playwright'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const guiDir = path.join(__dirname, '..')
const out = path.join(guiDir, 'verify-screenshot.png')

const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded', timeout: 120_000 })
  await page.waitForFunction(
    () => {
      const el = document.getElementById('root')
      return !!(el && (el.textContent || '').trim().length > 20)
    },
    { timeout: 120_000 }
  )
  await new Promise((r) => setTimeout(r, 1500))
  await page.screenshot({ path: out, fullPage: true })
} finally {
  await browser.close()
}

if (!existsSync(out)) {
  console.error('Screenshot was not written')
  process.exit(1)
}
console.log('Wrote', out)
