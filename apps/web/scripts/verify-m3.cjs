const { chromium } = require("playwright")
const { createClient } = require("@supabase/supabase-js")
const { randomUUID } = require("node:crypto")
const { mkdirSync, readFileSync } = require("node:fs")

const readEnv = (path) => Object.fromEntries(readFileSync(path, "utf8").split(/\r?\n/).filter((line) => line && !line.startsWith("#")).map((line) => { const separator = line.indexOf("="); return [line.slice(0, separator), line.slice(separator + 1)]; }))

async function main() {
  const webEnv = readEnv(".env.local")
  const supabase = createClient(webEnv.VITE_SUPABASE_URL, webEnv.VITE_SUPABASE_PUBLISHABLE_KEY)
  const { data: login, error } = await supabase.auth.signInWithPassword({ email: "admin@ares.local", password: "AresLocal!2026" })
  if (error || !login.session) throw error || new Error("session_missing")
  const headers = { Authorization: `Bearer ${login.session.access_token}`, "Content-Type": "application/json" }
  const aggregateId = `deal-m3-browser-${randomUUID()}`
  const fixture = await fetch("http://127.0.0.1:8000/api/v1/dev/fake-crm/events", { method: "POST", headers, body: JSON.stringify({ aggregate_id: aggregateId }) })
  if (!fixture.ok) throw new Error("browser_fixture_failed")
  const list = await (await fetch("http://127.0.0.1:8000/api/v1/opportunities", { headers })).json()
  const opportunity = list.items.find((item) => item.external_id === aggregateId)
  if (!opportunity) throw new Error("browser_opportunity_missing")

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
  await page.goto(`http://localhost:5173/opportunities/${opportunity.id}`, { waitUntil: "networkidle" })
  await page.getByRole("heading", { name: "Decisão e ação" }).waitFor()
  await page.getByRole("button", { name: /Gerar recomendação/ }).click()
  await page.getByText("Ação recomendada").waitFor()
  await page.getByText("require_approval").waitFor()
  await page.getByRole("button", { name: /^Aprovar$/ }).click()
  await page.getByText("Ação executada").waitFor({ timeout: 15000 })
  await page.getByRole("link", { name: /Aprovações/ }).click()
  await page.getByRole("heading", { name: "Fila de aprovações" }).waitFor()
  const overlay = await page.locator(".vite-error-overlay, #webpack-dev-server-client-overlay").count()
  const hasContent = (await page.locator("body").innerText()).trim().length > 0
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`http://localhost:5173/opportunities/${opportunity.id}`)
  await page.getByText("Ação executada").waitFor()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  const overflowElements = await page.evaluate(() => [...document.querySelectorAll("*")].filter((element) => element.getBoundingClientRect().right > document.documentElement.clientWidth + 1).slice(0, 12).map((element) => ({ tag: element.tagName, className: element.className, right: Math.round(element.getBoundingClientRect().right), width: Math.round(element.getBoundingClientRect().width) })))
  await page.keyboard.press("Tab")
  const focused = await page.evaluate(() => document.activeElement !== document.body)
  mkdirSync("test-results", { recursive: true })
  await page.screenshot({ path: "test-results/m3-decision-mobile-final.png", fullPage: true })
  await browser.close()
  const result = { opportunity: opportunity.id, overlay, hasContent, overflow, overflowElements, focused, consoleErrors, pageErrors }
  console.log(JSON.stringify(result))
  if (overlay || !hasContent || overflow || !focused || consoleErrors.length || pageErrors.length) process.exitCode = 1
}

main().catch((error) => { console.error(error); process.exitCode = 1 })
