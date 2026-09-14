const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const output = path.resolve(__dirname, '../../../output/playwright/m5-chat');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [], consoleErrors = [], layouts = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  try {
    await page.goto('http://localhost:5173/chat');
    await page.getByLabel('E-mail', { exact: true }).fill('admin@ares.local');
    await page.getByLabel('Senha', { exact: true }).fill('AresLocal!2026');
    await page.getByRole('button', { name: 'Entrar', exact: true }).click();
    await page.getByRole('heading', { name: 'Chat ARES', exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelectorAll('#chat-scope option').length > 1);
    const loaded = page.waitForResponse(r => r.url().includes('/chat/messages?'));
    await page.getByLabel('Oportunidade', { exact: true }).selectOption({ index: 1 });
    const response = await loaded;
    assert.equal(response.status(), 200);
    const snapshot = await response.json();
    assert(snapshot.context.tokens_upper_bound <= 2500);
    await page.locator('.chat-context').waitFor();
    assert.equal(await page.getByRole('button', { name: 'Enviar pergunta' }).isDisabled(), true);
    for (const theme of ['dark','light']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) {
        await page.getByRole('button', { name: theme === 'dark' ? 'Ativar modo escuro' : 'Ativar modo claro' }).click();
      }
      for (const width of [1440,820,700,390]) {
        await page.setViewportSize({ width, height: 1000 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const violations = await page.evaluate(async () => (await axe.run('.chat-page', {
          runOnly: { type:'tag', values:['wcag2a','wcag2aa','wcag21aa'] },
        })).violations.map(v => ({ id:v.id, targets:v.nodes.map(n=>n.target) })));
        assert.deepEqual(violations, []);
        await page.screenshot({ path: path.join(output, `chat-${theme}-${width}.png`), fullPage: true });
        layouts.push({ theme, width, violations });
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []);
    // Presentation-only simulated provider. No API mutation or model call.
    await page.route('**/chat/messages?*', route => route.fulfill({ json:{ ...snapshot, model_available:true } }));
    await page.getByRole('button', { name:'Atualizar conversa' }).click();
    await page.waitForFunction(() => !document.querySelector('#chat-text').disabled);
    await page.route('**/api/v1/chat/messages', route => route.fulfill({ contentType:'text/event-stream', body:
      'event: tool\ndata: {"name":"get_context","status":"completed"}\n\n' +
      'event: token\ndata: {"text":"Resposta sintética controlada"}\n\n' +
      'event: error\ndata: {"code":"model_response_failed","correlation_id":"synthetic-stream-check"}\n\n' }));
    await page.getByLabel('Sua pergunta', { exact:true }).fill('Resuma as evidências');
    await page.getByLabel('Sua pergunta', { exact:true }).focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Enviar pergunta');
    await page.keyboard.press('Enter');
    await page.getByText('Resposta sintética controlada', { exact:true }).waitFor();
    await page.getByText('get_context: concluído', { exact:true }).waitFor();
    await page.getByRole('alert').waitFor();
    assert((await page.getByRole('alert').innerText()).includes('synthetic-stream-check'));
    assert.deepEqual(errors, []);
    const report = { source:'real local API/context + controlled stream response', modelConfigured:snapshot.model_available,
      layouts, errors, consoleErrors, simulated:['tools','partial_text','stream_error'], keyboard:'Tab and Enter submit' };
    fs.writeFileSync(path.join(output,'report.json'), JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } catch(error) {
    await page.screenshot({ path:path.join(output,'failure.png'), fullPage:true }); throw error;
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode=1; });
