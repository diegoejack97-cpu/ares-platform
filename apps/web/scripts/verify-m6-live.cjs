/* Real local synthetic acceptance: no HTTP interception, no external delivery. */
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const output = path.resolve(__dirname, '../../../output/playwright/m6-live');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', recordVideo: { dir: output } });
  const page = await context.newPage();
  const errors = [], checks = [];
  page.on('pageerror', error => errors.push(error.message));
  const base = 'http://localhost:5173';
  const tag = Date.now();
  try {
    await page.goto(`${base}/licenses`);
    await page.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
    await page.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
    await page.getByRole('button', { name: 'Entrar', exact: true }).click();
    await page.getByRole('heading', { name: 'Licenças e convites' }).waitFor();
    await page.getByLabel('E-mail', { exact: true }).fill(`synthetic-m6-${tag}@example.invalid`);
    await page.getByLabel('Justificativa do convite').fill('Synthetic local M6 acceptance');
    await page.getByRole('button', { name: 'Registrar convite', exact: true }).click();
    await page.getByRole('button', { name: `Cancelar synthetic-m6-${tag}@example.invalid` }).waitFor();
    await page.getByLabel('Justificativa da alteração').fill('Synthetic invitation cancellation');
    await page.getByRole('button', { name: `Cancelar synthetic-m6-${tag}@example.invalid` }).click();
    await page.getByText(`synthetic-m6-${tag}@example.invalid · seller · cancelled`, { exact: true }).waitFor();
    checks.push('real invitation reservation and cancellation');
    await page.goto(`${base}/leads`);
    await page.getByLabel('Nome do lead').fill(`Synthetic M6 ${tag}`);
    await page.getByLabel('E-mail do lead').fill(`synthetic-lead-${tag}@example.invalid`);
    await page.getByRole('button', { name: 'Enviar para triagem', exact: true }).click();
    await page.getByRole('button', { name: `Synthetic M6 ${tag}`, exact: true }).click();
    await page.getByLabel('Motivo da decisão').fill('Synthetic human authorization for local CRM');
    await page.getByRole('button', { name: 'Confirmar criação no CRM', exact: true }).click();
    await page.getByText('Estado: created.', { exact: false }).waitFor();
    checks.push('lead creation confirmed in local source');
    await page.getByLabel('Nome do lead').fill(`Synthetic M6 ${tag} duplicate`);
    await page.getByLabel('E-mail do lead').fill(`synthetic-lead-${tag}@example.invalid`);
    await page.getByRole('button', { name: 'Enviar para triagem', exact: true }).click();
    await page.getByRole('button', { name: `Synthetic M6 ${tag} duplicate`, exact: true }).click();
    await page.getByRole('radio').first().check();
    await page.getByLabel('Motivo da decisão').fill('Synthetic duplicate reviewed by human');
    await page.getByRole('button', { name: 'Mesclar com selecionado' }).click();
    await page.getByText('Estado: merged.', { exact: false }).waitFor();
    await page.getByLabel('Motivo da decisão').fill('Synthetic undo preserving original identity');
    await page.getByRole('button', { name: 'Desfazer mesclagem' }).click();
    await page.getByText('Estado: pending.', { exact: false }).waitFor();
    checks.push('human merge and undo');
    await page.goto(`${base}/impact`);
    await page.getByText('Este relatório contém dados sintéticos', { exact: false }).waitFor();
    for (const format of ['CSV', 'PDF']) {
      const download = page.waitForEvent('download');
      await page.getByRole('button', { name: `Exportar ${format}` }).click();
      await (await download).saveAs(path.join(output, `impact.${format.toLowerCase()}`));
    }
    checks.push('real CSV and PDF exports with synthetic disclosure');
    const credentials = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../../output/runtime/m6-provider-credentials.json'), 'utf8'));
    await page.goto(`${base}/admin`);
    await page.getByLabel('E-mail do provedor').fill(credentials.email);
    await page.getByLabel('Senha do provedor').fill(credentials.password);
    await page.getByRole('button', { name: 'Entrar como provedor' }).click();
    await page.locator('.provider-tenants button').first().click();
    await page.getByRole('heading', { name: 'Cotas e licenças' }).waitFor();
    checks.push('dedicated provider real authentication and configuration read');
    for (const route of ['admin', 'licenses', 'leads', 'impact']) {
      if (route !== 'admin') await page.goto(`${base}/${route}`);
      await page.getByRole('heading', { level: 1 }).waitFor();
      for (const width of [1440, 700, 390]) {
        await page.setViewportSize({ width, height: 1000 });
        await page.addStyleTag({ content: '*,*::before,*::after{transition:none!important;animation:none!important}' });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${route} overflow ${width}`);
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const violations = await page.evaluate(async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } })).violations.map(v => ({ id:v.id, targets:v.nodes.map(n => n.target) })));
        assert.deepEqual(violations, [], `${route} accessibility ${width}`);
        await page.screenshot({ path: path.join(output, `${route}-${width}.png`), fullPage: true });
      }
      await page.keyboard.press('Tab');
      assert.notEqual(await page.evaluate(() => document.activeElement.tagName), 'BODY');
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ checks, responsive: [1440,700,390], errors }, null, 2));
    console.log(JSON.stringify({ checks, errors }));
  } catch(error) { await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }); throw error; }
  finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
