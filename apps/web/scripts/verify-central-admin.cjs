/* Local, real-session acceptance of provider and company admin boundaries. */
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../../..');
const credentials = JSON.parse(
  fs.readFileSync(path.join(root, 'output/runtime/m6-provider-credentials.json'), 'utf8'),
);
const output = path.join(root, 'output/playwright/central-admin');
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  try {
    await page.goto('http://localhost:5173/central-admin');
    await page.getByLabel('E-mail do provedor').fill(credentials.email);
    await page.getByLabel('Senha do provedor').fill(credentials.password);
    await page.getByRole('button', { name: 'Entrar como provedor' }).click();
    await page.getByRole('heading', { name: 'Empresas e contratos' }).waitFor();
    const first = page.locator('.provider-tenants button').first();
    assert(await first.count(), 'provider must see at least one company');
    const company = await first.textContent();
    await first.click();
    await page.getByRole('region', { name: 'Resumo do contrato' }).waitFor();
    assert.equal(await page.getByLabel('Capacidade de agentes ativos').count(), 1);
    assert.equal(await page.getByLabel('Capacidade de sentinelas ativas').count(), 1);
    const quota = {
      agents: await page.getByLabel('Capacidade de agentes ativos').inputValue(),
      sentinels: await page.getByLabel('Capacidade de sentinelas ativas').inputValue(),
    };
    await page.getByLabel('Capacidade de agentes ativos').focus();
    await page.keyboard.press('Tab');
    assert.equal(
      await page.evaluate(() => document.activeElement?.id),
      'sentinel_slots',
    );
    await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true });
    const mobileOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    assert.equal(mobileOverflow, false, 'provider page must not overflow mobile');

    await page.evaluate(() => localStorage.setItem('ares-theme', 'dark'));
    await page.goto('http://localhost:5173/central-admin');
    await page.getByRole('heading', { name: 'Empresas e contratos' }).waitFor();
    await page.locator('.provider-tenants button').first().click();
    await page.getByRole('region', { name: 'Resumo do contrato' }).waitFor();
    await page.screenshot({ path: path.join(output, 'mobile-dark.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: path.join(output, 'desktop-dark.png'), fullPage: true });

    const tenantPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    tenantPage.on('pageerror', (error) => errors.push(error.message));
    tenantPage.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });
    await tenantPage.goto('http://localhost:5173/radar');
    await tenantPage.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
    await tenantPage.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
    await tenantPage.getByRole('button', { name: 'Entrar', exact: true }).click();
    await tenantPage.locator('#ares-sidebar').waitFor();
    const licensesLink = tenantPage.locator('#ares-sidebar a[href="/licenses"]');
    const commandLink = tenantPage.locator('#ares-sidebar a[href="/command-center"]');
    await licensesLink.waitFor();
    await commandLink.waitFor();
    assert.equal(await tenantPage.locator('a[href="/central-admin"]').count(), 0);
    assert.equal(await licensesLink.count(), 1);
    assert.equal(await commandLink.count(), 1);
    await licensesLink.focus();
    await tenantPage.keyboard.press('Enter');
    await tenantPage.getByRole('heading', { name: 'Licenças e convites' }).waitFor();
    await tenantPage.locator('.license-summary').waitFor({ timeout: 20000 });
    await tenantPage.screenshot({ path: path.join(output, 'company-users.png'), fullPage: true });
    await commandLink.click();
    await tenantPage.getByRole('heading', { name: 'Command Center' }).waitFor();
    await tenantPage.getByRole('heading', { name: 'Agora' }).waitFor({ timeout: 30000 });
    await tenantPage.screenshot({ path: path.join(output, 'company-command-center.png'), fullPage: true });
    await tenantPage.setViewportSize({ width: 390, height: 844 });
    await tenantPage.getByRole('button', { name: 'Abrir menu' }).click();
    await tenantPage.locator('#ares-sidebar a[href="/licenses"]').click();
    await tenantPage.locator('.license-summary').waitFor({ timeout: 20000 });
    await tenantPage.waitForFunction(() => {
      const sidebar = document.querySelector('#ares-sidebar');
      return sidebar?.getAttribute('data-expanded') === 'false' && sidebar.getBoundingClientRect().right <= 1;
    });
    assert.equal(
      await tenantPage.evaluate(() => document.documentElement.scrollWidth > window.innerWidth),
      false,
      'company administration must not overflow mobile',
    );
    await tenantPage.screenshot({ path: path.join(output, 'company-users-mobile.png'), fullPage: true });
    await tenantPage.goto('http://localhost:5173/central-admin');
    await tenantPage.getByRole('heading', { name: 'Acesso do provedor' }).waitFor();
    assert.equal(await tenantPage.locator('.provider-tenants').count(), 0);
    assert.deepEqual(errors, []);
    const report = {
      company,
      quota,
      mobileOverflow,
      providerPanel: true,
      tenantAdminNoProviderLink: true,
      companyUsersInProduct: true,
      companyCommandCenterInProduct: true,
      companySessionCannotOpenProviderPanel: true,
      errors,
    };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
