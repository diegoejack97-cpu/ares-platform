const { chromium, expect } = require("@playwright/test");
const path = require("node:path");
const fs = require("node:fs");

// Read-only regression: authentication -> initial data -> manual + automatic refresh.
(async () => {
  const origin = process.env.ARES_WEB_URL || "http://localhost:5173";
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  const reads = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  const isOpportunities = (response) =>
    new URL(response.url()).pathname === "/api/v1/opportunities" &&
    response.request().method() === "GET";
  page.on("response", (response) => {
    if (isOpportunities(response))
      reads.push({ status: response.status(), at: Date.now() });
  });
  try {
    await page.goto(origin + "/radar");
    await page.locator('input[type="email"], .radar-page').first().waitFor();
    if (await page.locator('input[type="email"]').isVisible()) {
      await page.getByLabel("E-mail", { exact: true }).fill("admin@ares.local");
      await page.getByLabel("Senha", { exact: true }).fill("AresLocal!2026");
      await page.getByRole("button", { name: "Entrar", exact: true }).click();
    }
    await page
      .locator(".radar-table tbody tr")
      .first()
      .waitFor({ timeout: 30000 });
    const [manual] = await Promise.all([
      page.waitForResponse(isOpportunities),
      page
        .getByRole("button", { name: "Atualizar radar", exact: true })
        .click(),
    ]);
    expect(manual.status()).toBe(200);
    const payload = await manual.json();
    await expect(
      page.locator(".console-metrics .live-value").first(),
    ).toHaveAttribute("data-value", String(payload.items.length));
    const automatic = await page.waitForResponse(isOpportunities, {
      timeout: 22000,
    });
    expect(automatic.status()).toBe(200);
    const autoPayload = await automatic.json();
    await expect(
      page.locator(".console-metrics .live-value").first(),
    ).toHaveAttribute("data-value", String(autoPayload.items.length));
    await expect(
      page.getByRole("button", { name: "Atualizar radar", exact: true }),
    ).toBeEnabled();
    expect(errors).toEqual([]);
    const output = path.resolve(
      __dirname,
      "../../../output/playwright/live-data",
    );
    fs.mkdirSync(output, { recursive: true });
    await page.mouse.move(1000, 100);
    await page.keyboard.press("Escape");
    await expect(page.locator(".sidebar")).toHaveAttribute(
      "data-expanded",
      "false",
    );
    await expect
      .poll(async () =>
        Math.round((await page.locator(".sidebar").boundingBox()).width),
      )
      .toBe(76);
    await page.screenshot({
      path: path.join(output, "radar-restored.png"),
      fullPage: true,
    });
    const report = {
      origin,
      opportunities: autoPayload.items.length,
      source: autoPayload.source,
      reads,
      manualRefresh: true,
      automaticRefresh: true,
      errors,
    };
    fs.writeFileSync(
      path.join(output, "report.json"),
      JSON.stringify(report, null, 2),
    );
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    console.error(JSON.stringify({ origin, reads, errors }, null, 2));
    throw error;
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
