/* Read-only visual regression. Uses local synthetic login; never resets data. */
const { chromium, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const pass = process.env.ARES_VISUAL_PASS || 'final';
const output = path.resolve(__dirname, '../../../output/playwright/visual-upgrade', pass);
const origin = process.env.ARES_WEB_URL || 'http://localhost:5173';

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const errors = [], results = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  try {
    await page.goto(origin + '/radar');
    await page.locator('input[type="email"], .radar-page').first().waitFor({ timeout: 30000 });
    if (await page.locator('input[type="email"]').isVisible()) {
      await page.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
      await page.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
      await page.getByRole('button', { name: 'Entrar', exact: true }).click();
    }
    await page.locator('.radar-table tbody tr').first().waitFor({ timeout: 30000 });
    const detail = await page.getByRole('link', { name: 'Analisar oportunidade' }).getAttribute('href');
    const routes = [['/radar', 'radar'], ['/journal', 'journal'], ['/fake-crm', 'crm'], ['/approvals', 'approvals'], [detail, 'detail']];
    for (const theme of ['dark', 'light']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme)
        await page.getByRole('button', { name: theme === 'dark' ? 'Ativar modo escuro' : 'Ativar modo claro' }).click();
      for (const [route, name] of routes) {
        console.log(`Checking ${theme} ${route}`);
        await page.goto(origin + route);
        try { await page.locator('main h1').waitFor(); }
        catch (error) { await page.screenshot({ path: path.join(output, `failed-${name}-${theme}.png`), fullPage: true }); throw error; }
        if (name === 'radar') await page.locator('.radar-table tbody tr').first().waitFor();
        if (name === 'journal') await page.locator('table tbody tr').first().waitFor();
        await page.mouse.click(800, 60);
        for (const [width, height] of [[1920,1080], [1440,900], [1280,800], [820,1180], [390,844]]) {
          await page.setViewportSize({ width, height });
          await page.waitForTimeout(300);
          const metrics = await page.evaluate(() => ({ width: innerWidth, docWidth: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }));
          results.push({ route, theme, ...metrics });
          await page.screenshot({ path: path.join(output, `${name}-${theme}-${width}.png`), fullPage: true });
          expect(metrics.docWidth).toBeLessThanOrEqual(width);
        }
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const violations = await page.evaluate(async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } })).violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) })));
        results.push({ route, theme, axe: violations });
      }
    }
    expect(results.filter(r => r.axe?.length)).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ results, errors }, null, 2));
    console.log(JSON.stringify({ pass, screens: results.filter(r => r.width).length, overflows: results.filter(r => r.docWidth > r.width), axe: results.filter(r => r.axe?.length), errors }, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
