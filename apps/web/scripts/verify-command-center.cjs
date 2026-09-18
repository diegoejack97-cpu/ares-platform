/* Real local synthetic acceptance: no HTTP interception, no external delivery. */
const { chromium } = require("playwright-core");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
(async () => {
  const output = path.resolve(__dirname, "../../../output/playwright/command-center");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
    recordVideo: { dir: output },
  });
  const page = await context.newPage();
  const errors = [];
  const checks = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const base = process.env.ARES_WEB_URL || "http://localhost:5173";
  try {
    await page.goto(`${base}/command-center`);
    if (await page.getByLabel("E-mail", { exact: true }).isVisible().catch(() => false)) {
      await page.getByLabel("E-mail", { exact: true }).fill("admin@ares.local");
      await page.getByLabel("Senha", { exact: true }).fill("AresLocal!2026");
      await page.getByRole("button", { name: "Entrar", exact: true }).click();
    }
    await page.getByRole("heading", { name: "Command Center", level: 1 }).waitFor();
    await page.getByRole("region", { name: "Agora" }).waitFor();
    checks.push("real login and page read");

    const nav = page.getByRole("link", { name: "Command Center" }).first();
    assert.match(await nav.getAttribute("class"), /active/);
    assert.equal(await page.locator(".nav-item.future", { hasText: "Command Center" }).count(), 0);
    checks.push("nav link active, placeholder gone");

    await page.getByText("Não comprovado").first().waitFor();
    await page.getByText(/\d+ de \d+ execuções com custo medido/).first().waitFor();
    await page.getByText("Dados sintéticos.").waitFor();
    await page.getByText(/\d+ de \d+ abertas com prazo definido/).waitFor();
    const queue = page.getByRole("region", { name: /Fila prioritária/ });
    assert.ok((await queue.locator('a[href^="/opportunities/"]').count()) >= 1);
    checks.push("honest impact figures and prioritized queue");

    const frames = page.locator("[data-chart-frame]");
    await frames.first().waitFor();
    assert.equal(await frames.count(), 4);
    for (let index = 0; index < 4; index += 1) {
      const frame = frames.nth(index);
      await frame.getByRole("button", { name: /Tabela/ }).click();
      await frame.getByRole("table").waitFor();
      await frame.getByRole("button", { name: /Gráfico/ }).click();
      await frame.locator("svg").first().waitFor();
    }
    checks.push("four frames with table alternatives");

    await page.getByRole("button", { name: "Definição de Críticas" }).click();
    assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.id), "def-critical");
    checks.push("definition jump focuses the definition");

    await queue.locator('a[href^="/opportunities/"]').first().click();
    await page.waitForURL(/\/opportunities\/[0-9a-f-]{36}/);
    await page.goBack();
    await page.getByRole("heading", { name: "Command Center", level: 1 }).waitFor();
    checks.push("queue opens the opportunity");

    const response = page.waitForResponse((r) => r.url().includes("/command-center?days=7") && r.ok());
    await page.getByLabel("Período").selectOption("7");
    await response;
    await page.getByText(/\(7 d\)/).first().waitFor();
    checks.push("period switch requests the new window");

    for (const width of [1440, 700, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.addStyleTag({ content: "*,*::before,*::after{transition:none!important;animation:none!important}" });
      await page.waitForTimeout(400);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `overflow ${width}`);
      await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
      const violations = await page.evaluate(async () =>
        (await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } })).violations.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target) })),
      );
      assert.deepEqual(violations, [], `accessibility ${width}`);
      await page.screenshot({ path: path.join(output, `command-center-${width}.png`), fullPage: true });
    }
    checks.push("no overflow and no axe violations at 1440/700/390");

    await page.keyboard.press("Tab");
    assert.notEqual(await page.evaluate(() => document.activeElement.tagName), "BODY");

    await page.setViewportSize({ width: 1440, height: 1000 });
    for (const [label, theme] of [["Ativar modo claro", "light"], ["Ativar modo escuro", "dark"]]) {
      const toggle = page.getByRole("button", { name: label });
      if (await toggle.count()) {
        await toggle.click();
        assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
        await page.screenshot({ path: path.join(output, `command-center-${theme}.png`), fullPage: true });
      }
    }
    checks.push("keyboard focus and both themes");

    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, "report.json"), JSON.stringify({ checks, responsive: [1440, 700, 390], errors }, null, 2));
    console.log(JSON.stringify({ checks, errors }));
  } catch (error) {
    await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true });
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
