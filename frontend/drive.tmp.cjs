/**
 * Sign in and screenshot every page, collecting console errors and failed
 * requests. Verifies the app actually works with authentication enabled.
 */
const { chromium } = require('playwright');

const SHOTS = process.argv[2];
const PASSWORD = process.argv[3];

const PAGES = [
    ['dashboard', '/'],
    ['map', '/map'],
    ['wall', '/wall'],
    ['search', '/search'],
    ['alerts', '/alerts'],
    ['watchlist', '/watchlist'],
];

(async () => {
    const browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

    const errors = [];
    const failed = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)); });
    page.on('requestfailed', r => failed.push(`${r.method()} ${r.url().slice(0, 90)}`));
    page.on('response', r => {
        if (r.status() >= 400) failed.push(`${r.status()} ${r.url().slice(0, 90)}`);
    });

    await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
    await page.fill('input[type=password]', PASSWORD);

    const t0 = Date.now();
    await page.click('button[type=submit]');
    await page.waitForSelector('.app-layout', { timeout: 20000 }).catch(() => {});
    console.log(`login -> ${Date.now() - t0}ms, shell present: ${await page.locator('.app-layout').count() > 0}`);

    for (const [name, path] of PAGES) {
        const start = Date.now();
        await page.goto(`http://localhost:5173${path}`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(3500);
        await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
        const text = (await page.locator('body').innerText()).replace(/\s+/g, ' ').trim();
        console.log(`${name.padEnd(10)} ${String(Date.now() - start).padStart(5)}ms  ${text.length} chars`);
    }

    console.log('\nconsole errors:', errors.length);
    [...new Set(errors)].slice(0, 8).forEach(e => console.log('  ', e));
    console.log('failed requests:', failed.length);
    [...new Set(failed)].slice(0, 8).forEach(f => console.log('  ', f));

    await browser.close();
})();
