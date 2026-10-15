import { chromium } from 'playwright'
const SP = process.argv[2]
const base = 'http://127.0.0.1:8000'
const problems = []
const browser = await chromium.launch({ args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1360, height: 900 } })
page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) problems.push(`console.${m.type()}: ${m.text()}`) })
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
page.on('requestfailed', (r) => problems.push(`requestfailed: ${r.url()}`))
page.on('response', (r) => { if (r.status() >= 400) problems.push(`http ${r.status()}: ${r.url()}`) })
const steps = []
const ok = (name, cond, detail = '') => steps.push(`${cond ? 'PASS' : 'FAIL'}  ${name}${detail ? '  (' + detail + ')' : ''}`)

await page.goto(base + '/#/overview'); await page.waitForSelector('.tile')
ok('overview shows 5 repositories', (await page.locator('table').first().locator('tbody tr').count()) === 5)
ok('overview shows alerts', (await page.locator('.alert').count()) >= 5)
await page.screenshot({ path: `${SP}/overview.png`, fullPage: true })
await page.fill('input[aria-label="Search"]', 'PAY-142 partial refunds'); await page.click('button:has-text("Search")')
await page.waitForSelector('.hit'); ok('search returns hits with signals', (await page.locator('.hit .signal').count()) > 0)

await page.click('nav >> text=Graph'); await page.waitForSelector('svg .node')
ok('graph renders service nodes', (await page.locator('g.node.service').count()) === 5)
await page.click('g.node.service >> text=payments-api'); await page.waitForSelector('text=Points to')
ok('node detail shows ledger-core dependency', await page.locator('.card >> text=ledger-core').count() > 0)
await page.screenshot({ path: `${SP}/graph.png`, fullPage: true })

await page.click('nav >> text=Feature Planner'); await page.click('text=Generate plan')
await page.waitForSelector('text=Affected components', { timeout: 20000 })
const comps = await page.locator('.card:has(h3:text("Affected components")) .alert b').allTextContents()
ok('plan covers 4 services', ['payments-api', 'ledger-core', 'notify-svc', 'customer-portal'].every((s) => comps.includes(s)), comps.join(','))
ok('plan lists ADR-007 not ADR-002', (await page.locator('text=ADR-007').count()) > 0 && (await page.locator('.card:has(h3:text("Governing decisions")) >> text=ADR-002').count()) === 0)
ok('LED-88 risk surfaced', (await page.locator('text=LED-88').count()) > 0)
await page.locator('.signal.btn').first().click()
ok('evidence inspector opens', (await page.locator('dl dt:text("Evidence type")').count()) === 1)
await page.click('text=Approve plan'); await page.waitForSelector('text=Plan approved.')
ok('plan approval works', true)
await page.screenshot({ path: `${SP}/planner.png`, fullPage: true })

await page.click('nav >> text=Knowledge'); await page.waitForSelector('table tbody tr')
ok('knowledge lists facts', (await page.locator('table tbody tr').count()) >= 10)
await page.click('.filters >> text=superseded'); await page.waitForTimeout(400)
ok('superseded filter shows ADR-002 only', (await page.locator('table tbody tr').count()) === 1)
await page.click('.filters >> text=all statuses')
await page.fill('input[placeholder^="Something the org"]', 'Prefer outbox events for new ledger integrations'); await page.click('button:has-text("Remember")')
await page.waitForSelector('.muted[role=status]'); const rs = await page.locator('.muted[role=status]').innerText(); ok('/remember records candidate (idempotent)', rs.includes('candidate') || rs.includes('Already'), rs)
await page.screenshot({ path: `${SP}/knowledge.png`, fullPage: true })

await page.setViewportSize({ width: 390, height: 800 }); await page.goto(base + '/#/overview'); await page.waitForSelector('.tile')
const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
ok('no horizontal scroll at phone width', !overflow)
await browser.close()
console.log(steps.join('\n')); console.log('\nproblems:', problems.length ? '\n' + [...new Set(problems)].join('\n') : 'none')
