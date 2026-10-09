/* Read-only browser verification. Existing synthetic local account; no seed or CRM write. */
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const output = path.resolve(__dirname, '../../../output/playwright/m5-agents');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  const errors = [], consoleErrors = [], layouts = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  try {
    await page.goto('http://localhost:5173/agentes');
    await page.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
    await page.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
    await page.getByRole('button', { name: 'Entrar', exact: true }).click();
    await page.locator('.workspace').waitFor();
    const loaded = page.waitForResponse(r => r.url().includes('/api/v1/agents?days=30'));
    await page.goto('http://localhost:5173/agentes');
    const response = await loaded;
    assert.equal(response.status(), 200);
    const snapshot = await response.json();
    await page.locator('.agents-source').waitFor();
    assert.equal(await page.locator('.agent-record').count(), snapshot.items.length);
    assert(snapshot.items.every(item => item.cost_usd === null));
    await page.getByLabel('Período', { exact: true }).focus();
    const changed = page.waitForResponse(r => r.url().includes('/api/v1/agents?days=7'));
    await page.keyboard.press('Home');
    await page.keyboard.press('Enter');
    await changed;
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.includes('Atualizar leitura') && !b.disabled));
    await page.locator('.agents-source').waitFor();
    assert.equal(await page.getByLabel('Período', { exact: true }).inputValue(), '7');
    const focus = await page.getByLabel('Período', { exact: true }).evaluate(el => {
      const s = getComputedStyle(el);
      return { active: el === document.activeElement, outline: s.outlineStyle, shadow: s.boxShadow };
    });
    assert(focus.active);
    assert(focus.outline !== 'none' || focus.shadow !== 'none');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.textContent.trim()), 'Atualizar leitura');
    await page.getByLabel('Período', { exact: true }).selectOption('30');
    await page.locator('.agents-source').waitFor();
    for (const theme of ['dark', 'light']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) {
        await page.getByRole('button', { name: theme === 'dark' ? 'Ativar modo escuro' : 'Ativar modo claro' }).click();
      }
      for (const [width, height] of [[1920,1080],[1440,900],[1280,800],[820,1180],[390,844]]) {
        await page.setViewportSize({ width, height });
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
        assert.equal(overflow, false, `${theme} ${width}: overflow`);
        await page.screenshot({ path: path.join(output, `agents-${theme}-${width}.png`), fullPage: true });
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const violations = await page.evaluate(async () => (await axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa'] },
        })).violations.map(v => ({ id: v.id, targets: v.nodes.map(n=>n.target) })));
        assert.deepEqual(violations, [], `${theme} ${width}: accessibility`);
        layouts.push({ theme, width, overflow, violations });
      }
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);
    // Controlled presentation-only responses. Source data is never modified.
    await page.route('**/api/v1/agents?*', route => route.fulfill({ json: { ...snapshot, items: [] } }));
    await page.getByRole('button', { name: 'Atualizar leitura' }).click();
    await page.getByRole('heading', { name: 'Nenhuma execução neste período' }).waitFor();
    await page.unroute('**/api/v1/agents?*');
    await page.route('**/api/v1/agents?*', route => route.fulfill({ status: 403, json: {
      error: { code: 'access_denied', correlation_id: 'presentation-only-access-check' },
    } }));
    await page.getByRole('button', { name: 'Atualizar leitura' }).click();
    await page.getByText('Acesso indisponível', { exact: true }).waitFor();
    assert.equal(await page.locator('.agent-record').count(), 0);
    assert.equal(await page.locator('.agents-source').count(), 0);
    await page.unroute('**/api/v1/agents?*');
    await page.getByRole('button', { name: 'Tentar novamente' }).click();
    await page.locator('.agents-source').waitFor();
    assert.equal(await page.locator('.agent-record').count(), snapshot.items.length);
    assert.deepEqual(errors, []);
    const report = { source: 'real local API and PostgreSQL; existing synthetic runs',
      groups: snapshot.items.length, layouts, keyboard: focus, consoleErrorsBeforeSimulated403: [],
      errors, simulatedStates: ['empty','access_denied','retry_to_real_data'] };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
