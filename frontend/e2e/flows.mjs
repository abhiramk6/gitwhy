// Browser walk through every user flow on a running app (Northwind org on :8000), saving one viewport screenshot per flow.
// Usage: node flows.mjs <out-dir> [base-url] [flow]   (flow: ask|review|memory|people|plan|trace|sources)
// Needs `npm i playwright-core` somewhere on NODE_PATH and a Chromium headless shell (PLAYWRIGHT_CHROMIUM or ~/.cache/ms-playwright).
// Exits non-zero if any step fails or the page logs an error.
import { chromium } from 'playwright-core'
import os from 'os'
const OUT = process.argv[2]; const BASE = process.argv[3] || 'http://127.0.0.1:8000'; const only = process.argv[4]
const exe = process.env.PLAYWRIGHT_CHROMIUM || `${os.homedir()}/.cache/ms-playwright/chromium_headless_shell-1148/chrome-linux/headless_shell`
const browser = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1360, height: 860 } })
const problems = []
page.on('console', (m) => { if (m.type() === 'error') problems.push(`console: ${m.text()}`) })
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('fonts')) problems.push(`http ${r.status()} ${r.url()}`) })
const shot = async (name) => { await page.waitForTimeout(700); await page.screenshot({ path: `${OUT}/${name}.png` }); console.log('shot', name) }
const run = async (name, fn) => { if (only && only !== name) return; try { await fn() } catch (e) { problems.push(`${name}: ${e.message.split('\n')[0]}`) } }

await run('ask', async () => {
  await page.goto(BASE + '/#/ask'); await page.waitForSelector('.chip'); await shot('01-ask-start')
  await page.click('.chip:has-text("cursor pagination")')
  await page.waitForSelector('.answer .tag', { timeout: 120000 }); await page.waitForTimeout(900)
  await page.click('.answer .tag >> nth=0'); await page.waitForSelector('.col .words'); await shot('02-ask-answer-with-source')
})
await run('review', async () => {
  await page.goto(BASE + '/#/review'); await page.waitForSelector('.list li button')
  await page.click('.list li button:has-text("refunds listing")')
  await page.click('button:has-text("Draft review")'); await page.waitForSelector('.cm', { timeout: 120000 })
  await page.click('.cm .tag >> nth=0'); await page.waitForSelector('.col .words'); await shot('03-review-draft')
})
await run('memory', async () => {
  await page.goto(BASE + '/#/memory'); await page.waitForSelector('.list li button')
  await page.click('.list li button:has-text("Cursor pagination")'); await page.click('button:has-text("Trace what happened")')
  await page.waitForSelector('.verdict', { timeout: 120000 }); await shot('04-memory-timeline')
})
await run('people', async () => {
  await page.goto(BASE + '/#/people'); await page.waitForSelector('.list li button')
  await page.click('.list li button:has-text("Dana")'); await page.click('button:has-text("Prepare handover")')
  await page.waitForSelector('.answer, .sect .tag', { timeout: 120000 }); await shot('05-people-handover')
})
await run('plan', async () => {
  await page.goto(BASE + '/#/plan'); await page.click('button:has-text("Plan it")'); await page.waitForSelector('.turn .tag', { timeout: 180000 }); await shot('06-plan')
})
await run('trace', async () => {
  await page.goto(BASE + '/#/trace?f=' + encodeURIComponent('notify-svc:notify/dedupe.py')); await page.waitForSelector('.core li'); await shot('07-trace')
})
await run('sources', async () => { await page.goto(BASE + '/#/sources'); await page.waitForSelector('.tbl'); await shot('08-sources') })
console.log(problems.length ? 'PROBLEMS:\n' + problems.join('\n') : 'no problems')
await browser.close()
process.exit(problems.length ? 1 : 0)
