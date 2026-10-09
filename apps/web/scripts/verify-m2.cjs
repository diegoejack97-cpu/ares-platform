const { chromium } = require("playwright")
const { mkdirSync } = require("node:fs")

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const consoleErrors = []
  const pageErrors = []
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()) })
  page.on("pageerror", (error) => pageErrors.push(error.message))
  await page.goto("http://localhost:5173", { waitUntil: "networkidle" })
  await page.getByLabel("E-mail").fill("admin@ares.local")
  await page.getByLabel("Senha").fill("AresLocal!2026")
  await page.getByRole("button", { name: "Entrar" }).click()
  await page.getByRole("heading", { name: "Radar de receita recuperável" }).waitFor()
  await page.getByRole("link", { name: "Event Journal" }).click()
  await page.getByRole("heading", { name: "Event Journal" }).waitFor()
  await page.getByRole("button", { name: "Simular evento" }).click()
  await page.getByText("deal.updated").first().waitFor({ state: "visible" })
  await page.getByRole("link", { name: /Radar ARES/ }).click()
  await page.getByText("Expansão Serra Metais — Unidade Sul").first().waitFor()
  await page.locator(".risk-chart svg").waitFor({ state: "visible" })
  const rows = await page.locator(".radar-table tbody tr").count()
  const chart = await page.locator(".risk-chart svg").count()
  await page.locator(".row-link").first().click()
  await page.getByRole("heading", { name: "Por que agora" }).waitFor()
  const evidence = await page.locator(".evidence-card").count()
  const recommendationBoundary = await page.getByText("Recomendação ainda não gerada").count()
  const contextRef = await page.getByText("Context ref").count()
  mkdirSync("test-results", { recursive: true })
  await page.screenshot({ path: "test-results/m2-opportunity-detail-final.png", fullPage: true })
  await browser.close()
  const result = { rows, chart, evidence, recommendationBoundary, contextRef, consoleErrors, pageErrors }
  console.log(JSON.stringify(result))
  if (rows < 1 || chart !== 1 || evidence < 1 || recommendationBoundary !== 1 || contextRef !== 1 || consoleErrors.length || pageErrors.length) process.exitCode = 1
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
