const { chromium, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

// UI-contract verification only: intercepts pipeline requests, never changes CRM data.
(async () => {
  const output = path.resolve(process.cwd(), 'output/playwright/pipeline');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(60000);
  const errors = [];
  const commands = [];
  const stages = [{ id: 'new', label: 'Entrada' }, { id: 'qualification', label: 'Qualificação' }, { id: 'proposal', label: 'Proposta' }, { id: 'negotiation', label: 'Negociação' }, { id: 'won', label: 'Ganho' }, { id: 'lost', label: 'Perdido' }];
  const items = Array.from({ length: 18 }, (_, index) => ({ id: `canonical-${index}`, external_id: `deal-${index}`, title: `Negócio sintético ${index + 1} · distribuição industrial`, stage: stages[index % 6].id, value: index === 0 ? null : (index + 1) * 2470, currency: index === 0 ? null : 'BRL', version: 4, owner_id: 'seller-01', changed_at: new Date().toISOString(), synthetic: true, is_missing: false }));
  const snapshot = { items, stages, capabilities: { update_stage: true, read_deals: true }, permissions: { can_move: true, can_manage: false }, freshness_at: new Date().toISOString(), source: 'FakeCRM · teste de contrato visual', partial: false, missing_count: 0, next_cursor: null, connection: { id: 'synthetic-connection', provider: 'fake-crm-http', status: 'healthy' } };
  let conflict = true;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/v1/pipeline', (route) => route.fulfill({ json: snapshot }));
  await page.route('**/api/v1/pipeline/deals/*/stage', (route) => {
    commands.push(route.request().postDataJSON());
    return route.fulfill(conflict ? { status: 409, json: { detail: { code: 'version_conflict', correlation_id: 'synthetic-conflict' } } } : { json: { status: 'succeeded', correlation_id: 'synthetic-success' } });
  });
  try {
    await page.goto('http://localhost:5173/pipeline');
    await page.locator('input[type="email"], .pipeline-workspace').first().waitFor();
    if (await page.locator('input[type="email"]').isVisible()) {
      await page.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
      await page.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
      await page.getByRole('button', { name: 'Entrar', exact: true }).click();
      await page.locator('.workspace').waitFor();
      await page.goto('http://localhost:5173/pipeline');
    }
    await page.locator('.pipeline-deal').first().waitFor();
    const checks = [];
    for (const theme of ['dark', 'light']) {
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      for (const [width, height] of [[1920,1080],[1440,900],[1280,800],[768,1024],[390,844]]) {
        await page.setViewportSize({ width, height });
        await page.screenshot({ path: path.join(output, `pipeline-${theme}-${width}.png`), fullPage: true });
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        expect(overflow).toBe(false);
        checks.push({ theme, width, height, overflow });
      }
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByLabel('Mover Negócio sintético 1 · distribuição industrial para', { exact: true }).selectOption('qualification');
    await expect(page.getByRole('dialog')).toBeVisible();
    expect(commands.length).toBe(0);
    await page.getByRole('button', { name: 'Confirmar e executar', exact: true }).click();
    await expect(page.getByText(/Conflito de versão ou intento/)).toBeVisible();
    await page.screenshot({ path: path.join(output, 'pipeline-conflict.png'), fullPage: true });
    await page.getByRole('button', { name: 'Recarregar estado e revisar' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    conflict = false;
    await page.getByLabel('Mover Negócio sintético 1 · distribuição industrial para', { exact: true }).selectOption('qualification');
    await page.getByRole('button', { name: 'Confirmar e executar', exact: true }).click();
    await expect(page.getByText(/Mudança confirmada pelo CRM/)).toBeVisible();
    expect(commands[0].idempotency_key).not.toBe(commands[1].idempotency_key);
    await page.getByRole('button', { name: 'Arrastar Negócio sintético 1 · distribuição industrial', exact: true }).focus();
    await page.keyboard.press('Space');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(errors).toEqual([]);
    const report = { mode: 'mocked pipeline API; real frontend and local authentication', checks, confirmedOnly: true, conflictRequiresNewIntent: true, keyboardDragCancel: true, errors };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
