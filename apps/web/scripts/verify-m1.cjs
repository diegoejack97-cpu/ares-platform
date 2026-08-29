const { chromium } = require("playwright")

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const consoleErrors = []
  const pageErrors = []

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text())
  })
  page.on("pageerror", (error) => pageErrors.push(error.message))

  await page.goto("http://localhost:5173", { waitUntil: "networkidle" })
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
  await page.screenshot({
    path: "test-results/m1-dashboard.png",
    fullPage: true,
  })
  await browser.close()

  const result = {
    headingCount,
    bodyLength,
    rows,
    charts,
    imagesWithoutAlt,
    consoleErrors,
    pageErrors,
  }
  console.log(JSON.stringify(result))

  if (
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
