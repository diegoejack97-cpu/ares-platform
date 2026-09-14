/* Existing synthetic local data; no seed, CRM writes, or model calls. */
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const output = path.resolve(__dirname, '../../../output/playwright/m5-graph');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [], consoleErrors = [], layouts = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  try {
    await page.goto('http://localhost:5173/radar');
    await page.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
    await page.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
    await page.getByRole('button', { name: 'Entrar', exact: true }).click();
    const link = page.locator('a[href^="/opportunities/"]').first();
    await link.waitFor();
    const loaded = page.waitForResponse(r => /\/graph\?depth=2/.test(r.url()));
    await link.click();
    const response = await loaded;
    assert.equal(response.status(), 200);
    const snapshot = await response.json();
    assert(snapshot.edges.length > 0);
    const panel = page.locator('.evidence-graph');
    await panel.locator('svg').waitFor();
    assert.equal(await panel.locator('li').count(), snapshot.edges.length);
    const summary = panel.locator('summary').first();
    await summary.focus();
    await page.keyboard.press('Enter');
    assert.equal(await panel.locator('details').first().getAttribute('open'), '');
    assert((await panel.innerText()).includes(snapshot.edges[0].evidence_event_id));
    const changed = page.waitForResponse(r => /\/graph\?depth=1/.test(r.url()));
    await page.getByLabel('Profundidade', { exact: true }).selectOption('1');
    const shallow = await (await changed).json();
    assert(shallow.edges.every(e => e.depth === 1));
    await page.waitForFunction(n => document.querySelectorAll('.evidence-graph-list li').length === n, shallow.edges.length);
    await page.getByRole('button', { name: 'Ocultar desenho', exact: true }).click();
    assert.equal(await panel.locator('svg').count(), 0);
    assert.equal(await panel.locator('li').count(), shallow.edges.length);
    await page.getByRole('button', { name: 'Mostrar desenho', exact: true }).click();
    await page.getByLabel('Profundidade', { exact: true }).selectOption('2');
    await page.waitForFunction(n => document.querySelectorAll('.evidence-graph-list li').length === n, snapshot.edges.length);
    for (const theme of ['dark', 'light']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) {
        await page.getByRole('button', { name: theme === 'dark' ? 'Ativar modo escuro' : 'Ativar modo claro' }).click();
      }
      for (const width of [1440, 820, 700, 390]) {
        await page.setViewportSize({ width, height: 1000 });
        await panel.scrollIntoViewIfNeeded();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: path.join(output, `graph-${theme}-${width}.png`), fullPage: true });
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const violations = await page.evaluate(async () => (await axe.run('.evidence-graph', {
          runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa'] },
        })).violations.map(v => ({ id: v.id, targets: v.nodes.map(n=>n.target) })));
        assert.deepEqual(violations, [], `${theme} ${width}`);
        layouts.push({ theme, width, violations });
      }
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);
    await page.route('**/graph?*', route => route.fulfill({ json: { ...snapshot, nodes: [], edges: [] } }));
    await page.getByRole('button', { name: 'Atualizar grafo', exact: true }).click();
    await page.getByText('Nenhuma relação comprovada disponível', { exact: true }).waitFor();
    await page.unroute('**/graph?*');
    await page.route('**/graph?*', route => route.fulfill({ status: 404, json: { error: { code: 'graph_unavailable' } } }));
    await page.getByRole('button', { name: 'Atualizar grafo', exact: true }).click();
    await panel.getByRole('alert').waitFor();
    assert.equal(await panel.locator('.evidence-graph-meta').count(), 0);
    assert.equal(await panel.locator('li').count(), 0);
    await page.unroute('**/graph?*');
    await page.getByRole('button', { name: 'Atualizar grafo', exact: true }).click();
    await panel.locator('svg').waitFor();
    assert.deepEqual(errors, []);
    const report = { source: 'real local API and PostgreSQL', edges: snapshot.edges.length, layouts,
      keyboard: 'Enter expands evidence', errors, consoleErrorsBeforeSimulated404: [],
      simulatedStates: ['empty', 'access_denied', 'retry_to_real_data'] };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
