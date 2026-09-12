/* Read-only browser checks against an already running local ARES stack. */
const { chromium, expect } = require("@playwright/test");
const path = require("node:path");
const fs = require("node:fs");
const origin = process.env.ARES_WEB_URL || "http://localhost:5173";
const output = path.resolve(
  __dirname,
  "../../../output/playwright/observatory",
);

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    colorScheme: "dark",
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [],
    results = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  try {
    await page.goto(origin + "/radar");
    await page
      .locator('input[type="email"], .radar-page')
      .first()
      .waitFor({ timeout: 30000 });
    if (await page.locator('input[type="email"]').isVisible()) {
      await page.getByLabel("E-mail", { exact: true }).fill("admin@ares.local");
      await page.getByLabel("Senha", { exact: true }).fill("AresLocal!2026");
      await page.getByRole("button", { name: "Entrar", exact: true }).click();
    }
    await page
      .locator(".radar-table tbody tr")
      .first()
      .waitFor({ timeout: 30000 });
    await page.mouse.move(800, 100);
    await page.mouse.click(900, 80);
    const sidebar = page.locator(".sidebar");
    await expect(sidebar).toHaveAttribute("data-expanded", "false");
    const rail = await page.evaluate(() => {
      const styles = getComputedStyle(document.documentElement);
      return {
        closed: Number.parseInt(styles.getPropertyValue("--rail-w"), 10),
        open: Number.parseInt(styles.getPropertyValue("--rail-w-open"), 10),
      };
    });
    const before = await page.locator(".page-header").boundingBox();
    expect(Math.round((await sidebar.boundingBox()).width)).toBe(rail.closed);

    // Hover must not open the rail: an accidental pass of the mouse cannot reflow the workspace.
    await sidebar.hover();
    await expect(sidebar).toHaveAttribute("data-expanded", "false");
    const hovered = await page.locator(".page-header").boundingBox();
    expect(hovered.x).toBe(before.x);

    // Opening is deliberate, and it pushes the workspace instead of covering it.
    await page.getByRole("button", { name: "Abrir menu", exact: true }).click();
    await expect(sidebar).toHaveAttribute("data-expanded", "true");
    expect(Math.round((await sidebar.boundingBox()).width)).toBe(rail.open);
    const opened = await page.locator(".page-header").boundingBox();
    expect(Math.round(opened.x - before.x)).toBe(rail.open - rail.closed);

    await page.getByRole("button", { name: "Recolher menu" }).first().click();
    await expect(sidebar).toHaveAttribute("data-expanded", "false");
    const restored = await page.locator(".page-header").boundingBox();
    expect(restored.x).toBe(before.x);

    await sidebar.getByRole("link", { name: /Radar ARES/ }).focus();
    await expect(sidebar).toHaveAttribute("data-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(sidebar).toHaveAttribute("data-expanded", "false");
    results.push({
      check: "menu: hover inerte / clique empurra / teclado / Escape",
      ok: true,
    });

    expect(await page.locator(".radar-table tbody tr").count()).toBe(5);
    await page.locator(".radar-table-wrap").evaluate((el) => {
      el.scrollTop = el.scrollHeight;
      el.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await expect
      .poll(() => page.locator(".radar-table tbody tr").count())
      .toBeGreaterThan(5);
    results.push({
      check: "fila: cinco iniciais e revelação por rolagem",
      ok: true,
    });
    const frames = page.locator("[data-chart-frame]");
    expect(await frames.count()).toBe(4);
    for (let i = 0; i < 4; i++) {
      await frames
        .nth(i)
        .getByRole("button", { name: "Tabela", exact: true })
        .click();
      await expect(frames.nth(i).getByRole("table")).toBeVisible();
      await frames
        .nth(i)
        .getByRole("button", { name: "Gráfico", exact: true })
        .click();
      await expect(frames.nth(i).locator(".ares-chart-host svg")).toBeVisible();
    }
    results.push({ check: "4 gráficos e 4 alternativas em tabela", ok: true });
    const detail = await page
      .getByRole("link", { name: "Analisar oportunidade" })
      .getAttribute("href");
    await page.getByRole("button", { name: "Ativar modo claro" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await page.locator(".radar-table tbody tr").first().waitFor();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    results.push({ check: "tema persistido depois de recarregar", ok: true });

    for (const theme of ["dark", "light"]) {
      const current = await page.locator("html").getAttribute("data-theme");
      if (current !== theme)
        await page
          .getByRole("button", {
            name: theme === "dark" ? "Ativar modo escuro" : "Ativar modo claro",
          })
          .click();
      for (const [route, name] of [
        ["/radar", "radar"],
        ["/journal", "journal"],
        ["/fake-crm", "crm"],
        ["/approvals", "approvals"],
        [detail, "detail"],
      ]) {
        await page.goto(origin + route);
        await page.locator("main h1").waitFor();
        if (name === "radar")
          await page.locator(".radar-table tbody tr").first().waitFor();
        await page.mouse.move(800, 65);
        await page.mouse.click(900, 80);
        for (const width of [1440, 1024, 390]) {
          await page.setViewportSize({ width, height: 1000 });
          await page.waitForTimeout(350);
          const metrics = await page.evaluate(() => ({
            width: innerWidth,
            docWidth: document.documentElement.scrollWidth,
            invalid: /NaN|undefined|Infinity/.test(
              document.querySelector("main").innerText,
            ),
          }));
          results.push({ route, theme, ...metrics });
          await page.screenshot({
            path: path.join(output, `${name}-${theme}-${width}.png`),
            fullPage: true,
          });
        }
        await page.setViewportSize({ width: 1440, height: 1000 });
        await page.addScriptTag({
          path: require.resolve("axe-core/axe.min.js"),
        });
        const violations = await page.evaluate(async () =>
          (
            await axe.run(document, {
              runOnly: {
                type: "tag",
                values: ["wcag2a", "wcag2aa", "wcag21aa"],
              },
            })
          ).violations.map((v) => ({
            id: v.id,
            impact: v.impact,
            nodes: v.nodes.map((n) => ({
              target: n.target,
              summary: n.failureSummary,
            })),
          })),
        );
        results.push({ route, theme, axe: violations });
      }
    }
    await page.goto(origin + "/radar");
    await page.locator(".radar-table tbody tr").first().waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Abrir menu", exact: true }).click();
    await expect(sidebar).toHaveAttribute("data-expanded", "true");
    // Narrow screens get an overlay drawer, so the page behind it must be covered and locked.
    await expect(page.locator(".sidebar-scrim")).toBeVisible();
    expect(
      await page.evaluate(() => getComputedStyle(document.body).overflow),
    ).toBe("hidden");
    await page.keyboard.press("Escape");
    await expect(sidebar).toHaveAttribute("data-expanded", "false");
    await expect(page.locator(".sidebar-scrim")).toHaveCount(0);
    results.push({ check: "menu mobile: drawer, scrim e trava de rolagem", ok: true });
    expect(errors).toEqual([]);
    expect(
      results.filter(
        (r) => r.docWidth > r.width || r.invalid || (r.axe && r.axe.length),
      ),
    ).toEqual([]);
  } finally {
    const report = { results, errors };
    fs.writeFileSync(
      path.join(output, "report.json"),
      JSON.stringify(report, null, 2),
    );
    console.log(JSON.stringify(report, null, 2));
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
