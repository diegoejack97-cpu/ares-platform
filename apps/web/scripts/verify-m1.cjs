const { chromium } = require("playwright")
const { mkdirSync } = require("node:fs")

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const consoleErrors = []
  const pageErrors = []

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text())
  })
  page.on("pageerror", (error) => pageErrors.push(error.message))

  await page.goto("http://localhost:5173/journal", { waitUntil: "networkidle" })
  const loginHeading = await page
    .getByRole("heading", { name: "Entrar no ambiente" })
    .count()
  await page.getByLabel("E-mail").fill("admin@ares.local")
  await page.getByLabel("Senha").fill("AresLocal!2026")
  await page.getByRole("button", { name: "Entrar" }).click()
  await page.getByRole("heading", { name: "Event Journal" }).waitFor()
  const headingCount = await page
    .getByRole("heading", { name: "Event Journal" })
    .count()
  const bodyLength = (await page.locator("body").innerText()).trim().length

  await page.getByRole("button", { name: "Simular evento" }).click()
  await page.getByText("deal.updated").first().waitFor({ state: "visible" })
  await page.locator(".event-chart canvas").waitFor({ state: "visible" })
  await page.waitForTimeout(800)

  const rows = await page.locator("tbody tr").count()
  const charts = await page.locator(".event-chart canvas").count()
  const imagesWithoutAlt = await page.locator("img:not([alt])").count()
  mkdirSync("test-results", { recursive: true })
  await page.screenshot({
    path: "test-results/m1-dashboard.png",
    fullPage: true,
  })
  await browser.close()

  const result = {
    headingCount,
    loginHeading,
    bodyLength,
    rows,
    charts,
    imagesWithoutAlt,
    consoleErrors,
    pageErrors,
  }
  console.log(JSON.stringify(result))

  if (
    loginHeading !== 1 ||
    headingCount !== 1 ||
    rows < 1 ||
    charts !== 1 ||
    consoleErrors.length > 0 ||
    pageErrors.length > 0
  ) {
    process.exitCode = 1
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
