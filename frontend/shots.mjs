import { chromium } from 'playwright'
import fs from 'fs'

const OUT = 'C:/Users/Admin/AppData/Local/Temp/claude/d--Sentinel-Hackathone/68e6b571-dc2e-4e10-91db-f4792630746c/scratchpad/shots'
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1600, height: 950 }, deviceScaleFactor: 1 })
const page = await ctx.newPage()

const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)) })
page.on('pageerror', e => errors.push('PAGEERROR: ' + String(e).slice(0, 200)))

async function shot(name, ms = 2500) {
  await page.waitForTimeout(ms)
  await page.screenshot({ path: `${OUT}/${name}.png` })
  console.log('shot', name)
}

// 1. Login
await page.goto('http://localhost:5173/', { waitUntil: 'networkidle', timeout: 60000 })
await shot('01-login', 1800)

// Sign in as state admin
await page.fill('input[type=email]', 'admin@sentinel.gujarat.gov.in')
await page.fill('input[type=password]', 'sentinel-demo-2026')
await page.click('button[type=submit]')
await page.waitForTimeout(4000)
await shot('02-dashboard', 3000)

for (const [path, name, wait] of [
  ['/map', '03-map', 6000],
  ['/search', '04-search', 2500],
  ['/alerts', '05-alerts', 3000],
  ['/watchlist', '06-watchlist', 2500],
  ['/wall', '07-wall', 9000],
]) {
  await page.goto('http://localhost:5173' + path, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await shot(name, wait)
}

// Search flow: type a plate and search
await page.goto('http://localhost:5173/search', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(1500)
const input = page.locator('input[placeholder="GJ01AB1234"]')
await input.fill('GJ01AB1234')
await page.keyboard.press('Enter')
await shot('08-search-results', 4000)

console.log('\n=== CONSOLE ERRORS ===')
console.log(errors.length ? errors.slice(0, 12).join('\n') : '(none)')
await browser.close()
