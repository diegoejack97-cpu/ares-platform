/* Real local flow. Imports synthetic CRM records, never resets existing ARES data. */
const { chromium, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const output = path.resolve(__dirname, '../../../output/playwright/m4-live');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(30000);
  const errors = [], results = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto('http://localhost:5173/pipeline');
    if (await page.locator('input[type="email"]').isVisible()) {
      await page.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
      await page.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
      await page.getByRole('button', { name: 'Entrar', exact: true }).click();
      await page.locator('.workspace').waitFor();
      await page.goto('http://localhost:5173/pipeline');
    }
    await page.getByRole('button', { name: 'Integração e cargas', exact: true }).click();
    await page.getByRole('heading', { name: 'Contrato de campos e etapas' }).waitFor();
    if (await page.locator('.pipeline-section-heading code').textContent() === 'versão 0') {
      const saved = page.waitForResponse(r => r.url().endsWith('/integrations/mapping') && r.request().method() === 'PUT');
      await page.getByRole('button', { name: 'Validar e ativar mapeamento' }).click();
      expect((await saved).status()).toBe(200);
    }
    const accepted = page.waitForResponse(r => r.url().endsWith('/integrations/sync') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Reconciliar funil', exact: true }).click();
    const acceptedResponse = await accepted;
    expect(acceptedResponse.status()).toBe(202);
    const acceptedJob = await acceptedResponse.json();
    await expect(page.locator('.pipeline-jobs li').first()).toContainText(acceptedJob.id, { timeout: 120000 });
    await expect(page.locator('.pipeline-deal')).toHaveCount(60, { timeout: 120000 });
    await expect(page.locator('.pipeline-jobs li').first()).toContainText('Concluído', { timeout: 120000 });
    const refreshed = page.waitForResponse(r => r.url().endsWith('/api/v1/pipeline') && r.request().method() === 'GET');
    await page.getByRole('button', { name: 'Atualizar leitura', exact: true }).click();
    expect((await refreshed).status()).toBe(200);
    await page.getByRole('button', { name: 'Fechar integração', exact: true }).click();
    const card = page.locator('.pipeline-deal').first();
    const title = await card.locator('h3').textContent();
    const column = card.locator('xpath=ancestor::section[contains(@class,"pipeline-column")]');
    const originalLabel = await column.locator('h2').textContent();
    const target = await card.locator('select option').nth(1).getAttribute('value');
    const versionBefore = await card.locator('.pipeline-deal-facts').textContent();
    await card.locator('select').selectOption(target);
    await expect(page.getByRole('dialog')).toBeVisible();
    const written = page.waitForResponse(r => /\/pipeline\/deals\/[^/]+\/stage$/.test(r.url()) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Confirmar e executar', exact: true }).click();
    const writeResponse = await written;
    expect(writeResponse.status()).toBe(200);
    const receipt = await writeResponse.json();
    expect(receipt.status).toBe('succeeded');
    expect(receipt.ares_intervention).toBe(false);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const moved = page.locator('.pipeline-deal').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
    await expect(moved.locator('.pipeline-deal-facts')).not.toHaveText(versionBefore);
    // Restore source stage through the same human-confirmed UI. Both receipts remain auditable.
    await moved.locator('select').selectOption({ label: originalLabel });
    const restored = page.waitForResponse(r => /\/pipeline\/deals\/[^/]+\/stage$/.test(r.url()) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Confirmar e executar', exact: true }).click();
    expect((await restored).status()).toBe(200);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    for (const theme of ['dark', 'light']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme)
        await page.getByRole('button', { name: theme === 'dark' ? 'Ativar modo escuro' : 'Ativar modo claro' }).click();
      for (const [width, height] of [[1920,1080],[1440,900],[1280,800],[820,1180]]) {
        await page.setViewportSize({ width, height });
        await page.screenshot({ path: path.join(output, `pipeline-${theme}-${width}.png`), fullPage: true });
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
        expect(overflow).toBe(false);
        results.push({ theme, width, overflow });
      }
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
    const violations = await page.evaluate(async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa'] } })).violations.map(v => ({ id: v.id, nodes: v.nodes.map(n=>n.target) })));
    expect(violations).toEqual([]);
    expect(errors).toEqual([]);
    const report = { source: 'real API + real local DB + synthetic HTTP CRM', imported: 60,
      mapping: 'validated', sync: 'completed', move: 'externally confirmed', restored: true,
      correlation_id: receipt.correlation_id, ares_intervention: false, results, violations, errors };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    throw error;
  } finally { await browser.close(); }
})().catch(e=>{ console.error(e); process.exitCode=1; });
