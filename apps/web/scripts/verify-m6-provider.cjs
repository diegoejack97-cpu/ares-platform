/* Real authentication/denial; positive UI uses explicitly intercepted synthetic responses. */
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const output = path.resolve(__dirname, '../../../output/playwright/m6-provider');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto('http://localhost:5173/radar');
    await page.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
    await page.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
    await page.getByRole('button', { name: 'Entrar', exact: true }).click();
    await page.locator('.workspace').waitFor();
    const productSession = await page.evaluate(() => Object.entries(localStorage).filter(([k]) => k.includes('auth-token')));
    assert(productSession.length > 0);
    await page.goto('http://localhost:5173/admin');
    await page.getByLabel('E-mail do provedor').fill('admin@ares.local');
    await page.getByLabel('Senha do provedor').fill('AresLocal!2026');
    const denial = page.waitForResponse(r => r.url().includes('/api/v1/admin/tenants'));
    await page.getByRole('button', { name: 'Entrar como provedor' }).click();
    assert.equal((await denial).status(), 403);
    await page.getByText('Esta conta não tem acesso de provedor. Use a conta dedicada.').waitFor();
    assert.equal(await page.locator('#tenant-name').count(), 0);
    assert.deepEqual(await page.evaluate(() => Object.entries(localStorage).filter(([k]) => k.includes('auth-token'))), productSession);
    const tenant = { id: '30000000-0000-0000-0000-000000000006', name: 'Tenant sintético M6', slug: 'teste-m6', status: 'active', version: 1, created_at: '2026-09-15T12:00:00Z', updated_at: '2026-09-15T12:00:00Z' };
    let command;
    await page.route('**/api/v1/admin/tenants**', route => {
      const request = route.request();
      if (request.method() === 'POST') { command = request.postDataJSON(); return route.fulfill({ status: 409, json: { error: { code: 'version_conflict', correlation_id: 'synthetic-conflict' } } }); }
      return route.fulfill({ json: request.url().endsWith(tenant.id) ? { tenant, entitlements: [{ module: 'ares_connect', status: 'active', granted_at: tenant.created_at, expires_at: null }] } : { items: [tenant], next_cursor: null } });
    });
    await page.getByRole('button', { name: 'Tentar novamente' }).click();
    await page.getByRole('button', { name: tenant.name }).click();
    await page.getByLabel('Módulo', { exact: true }).selectOption('ares_connect');
    assert(await page.locator('option[value="ares_crm"]').isDisabled());
    await page.getByLabel('Motivo da alteração', { exact: true }).fill('Teste sintético de conflito');
    await page.getByRole('button', { name: 'Salvar módulo' }).click();
    await page.getByText('A configuração mudou ou conflita com outro registro. Recarregue antes de salvar.').waitFor();
    assert.equal(command.expected_version, 1);
    assert.equal(command.reason, 'Teste sintético de conflito');
    const layouts = [];
    // Inspect settled theme colors, excluding intermediate transition frames.
    await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; animation: none !important; }' });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => { document.documentElement.dataset.theme=theme; document.documentElement.classList.toggle('dark',theme==='dark'); }, theme);
      for (const width of [1440, 700, 390]) {
        await page.setViewportSize({ width, height: 900 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const violations = await page.evaluate(async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa'] } })).violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)})));
        assert.deepEqual(violations, [], `${theme} ${width}`);
        await page.screenshot({ path: path.join(output, `${theme}-${width}.png`), fullPage: true });
        layouts.push({ theme, width });
      }
    }
    await page.getByLabel('Nome', { exact: true }).focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'tenant-slug');
    await page.getByRole('button', { name: 'Sair do provedor' }).click();
    await page.getByRole('heading', { name: 'Acesso do provedor' }).waitFor();
    assert.deepEqual(await page.evaluate(() => Object.entries(localStorage).filter(([k]) => k.includes('auth-token'))), productSession);
    assert.deepEqual(errors, []);
    const report = { real: ['product admin denied 403', 'independent session storage'], simulated: ['tenant directory','entitlement conflict','funnel exclusion'], layouts, keyboard: true, errors };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } catch(error) { await page.screenshot({ path:path.join(output,'failure.png'),fullPage:true }); throw error; }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
