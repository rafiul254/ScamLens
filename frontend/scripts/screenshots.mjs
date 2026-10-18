/**
 * Real screenshots of the running app, for the README and the submission.
 *
 *   cd frontend && node scripts/screenshots.mjs
 *
 * It drives the actual UI at a phone viewport (390×844) — no mock-ups. If the
 * backend is unreachable the script fails loudly rather than producing a
 * pretty but fake image.
 *
 * The default language is English, so the set is English-first; the last two shots show the
 * Bangla verdict and the one-tap "read it in English" control, which is the whole point of a
 * four-language product.
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(here, '../../docs/screenshots')
const BASE = process.env.BASE ?? 'http://localhost:5173'

mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  locale: 'en-GB',
  colorScheme: 'light',
})
const page = await context.newPage()
await page.addInitScript(() => {
  document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style')
    // Full-page screenshots stitch scroll frames, which makes position:fixed chrome
    // appear in the middle of the image. Pin it to the document flow for captures.
    style.textContent = 'nav[aria-label="Main"], header{position:static !important}'
    document.head.appendChild(style)
  })
})
// The settings dialog has two "close" affordances; click the labelled ✕ reliably.
const closeSettings = async () => {
  await page.locator('button[aria-label="Close"], button[aria-label="বন্ধ"]').first().click()
}
const shot = async (name) => {
  await page.screenshot({ path: `${outDir}/${name}.png`, fullPage: true })
  console.log(`  ✓ docs/screenshots/${name}.png`)
}

page.on('pageerror', (err) => {
  console.error('  ! page error:', err.message)
})

console.log(`Capturing ${BASE} …`)
await page.goto(BASE, { waitUntil: 'networkidle' })

// Onboarding (screen 1) → skip
await page.waitForTimeout(400)
await shot('01-onboarding')
await page.getByRole('button', { name: /skip/i }).click()

// Home, English
await page.waitForTimeout(600)
await shot('02-home')

// A real analysis through the API, in English (Link tab is deterministic and fast)
await page.getByRole('tab', { name: /link/i }).click()
await page.getByRole('textbox').fill('http://bkash-verify-login.tk/account')
await page.getByRole('button', { name: /check this message/i }).click()
await page.waitForSelector('text=/scam|careful|safe/i', { timeout: 30000 })
// A link carries no prose, so the API answers in the interface language. If a card offering
// a re-run appears, use it, then capture the English verdict.
const readInEnglishLink = page.getByRole('button', { name: /read it in english/i })
if (await readInEnglishLink.count()) {
  await readInEnglishLink.click()
  await page.waitForTimeout(2500)
}
await page.waitForTimeout(1400) // let the gauge finish animating
await shot('03-result-english-scam')

// Expand the evidence panel
await page.getByRole('button', { name: /evidence the ai used/i }).click()
await page.waitForTimeout(500)
await shot('04-evidence')
await page.getByRole('button', { name: /what the agent did/i }).click()
await page.waitForTimeout(500)
await shot('05-agent-trace')

// Learn tab
await page.getByRole('link', { name: /learn/i }).first().click()
await page.waitForTimeout(900)
await shot('06-learn')

// Benchmark
await page.getByRole('link', { name: /benchmark/i }).first().click()
await page.waitForTimeout(1400)
await shot('07-benchmark')

// History
await page.getByRole('link', { name: /history/i }).first().click()
await page.waitForTimeout(900)
await shot('08-history')

// A Bangla message: the verdict comes back in Bangla …
await page.goto(BASE, { waitUntil: 'networkidle' })
await page.getByRole('tab', { name: /paste text/i }).click()
await page.getByRole('textbox').first().fill(
  'প্রিয় গ্রাহক, আপনার বিকাশ একাউন্ট সাময়িকভাবে বন্ধ করা হয়েছে। চালু রাখতে এই ওটিপি 445566 সহায়ক কর্মকর্তাকে জানান।',
)
await page.getByRole('button', { name: /check this message/i }).click()
await page.waitForSelector('text=/প্রতারণা|সাবধান|নিরাপদ/', { timeout: 30000 })
await page.waitForTimeout(1200)
await shot('09-bangla-verdict')

// … and one tap re-runs it for an English reader
const readInEnglish = page.getByRole('button', { name: /read it in english/i })
if (await readInEnglish.count()) {
  await readInEnglish.click()
  await page.waitForTimeout(2000)
  await shot('10-read-in-english')
} else {
  console.error('  ! the "read it in English" control did not appear')
}

// Dark mode on the result screen
await page.getByTestId('open-settings').click()
await page.getByRole('switch', { name: /dark/i }).check()
await closeSettings()
await page.waitForTimeout(900)
await shot('11-dark-result')

await browser.close()
console.log('Done.')
