/* Real local read, then isolated synthetic presentation fixtures without chat writes. */
const { chromium } = require("playwright-core");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const endpoint = /\/api\/v1\/chat\/messages(?:\?.*)?$/;
const sse = (events) =>
  events
    .map(
      ([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    )
    .join("");
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
const demoContext = {
  context_ref: "00000000-0000-4000-8000-000000000001",
  content: JSON.stringify({
    note: "Dados sintéticos de demonstração",
    opportunities: [],
  }),
  content_hash: "synthetic-browser-verification",
  tokens_upper_bound: 96,
  token_limit: 8000,
  count_method: "utf8_bytes_upper_bound",
  citations: [],
  truncated: false,
  captured_at: "2026-09-26T12:00:00Z",
  source: "Dados sintéticos de demonstração",
};
const markdown = [
  "## Comparativo de demonstração",
  "",
  "**Dados sintéticos.** Valores apenas para validar a apresentação.",
  "",
  "| Oportunidade | Valor | Situação |",
  "| --- | ---: | --- |",
  "| Demonstração Alfa | R$ 12.500,00 | Em análise |",
  "| Demonstração Beta | R$ 8.250,00 | Em proposta |",
  "",
  "### Próximos passos",
  "- Confirmar o próximo contato.",
  "- Consultar as evidências disponíveis.",
  "",
  "Identificador técnico de demonstração: `demo-" + "x".repeat(90) + "`.",
  "",
  "[Fonte de demonstração](https://example.com/demonstracao)",
  "[Link inseguro](javascript:alert(1))",
  '<img src="invalid-demo-image" onerror="window.__chatUnsafeHtml = true">',
  "<script>window.__chatUnsafeHtml = true</script>",
].join("\n");

(async () => {
  const output = path.resolve(__dirname, "../../../output/playwright/m5-chat");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  page.setDefaultTimeout(30_000);
  const errors = [],
    consoleErrors = [],
    expectedConsoleErrors = [],
    layouts = [],
    checks = [];
  let syntheticView = false,
    expectedHttpStatus = null;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const item = { text: message.text(), url: message.location().url };
    if (
      expectedHttpStatus &&
      endpoint.test(item.url) &&
      item.text.includes(`status of ${expectedHttpStatus}`)
    ) {
      expectedConsoleErrors.push(item);
    } else consoleErrors.push(item);
  });
  const base = process.env.ARES_WEB_URL || "http://localhost:5173";
  const readResponse = () =>
    page.waitForResponse(
      (r) => endpoint.test(r.url()) && r.request().method() === "GET",
    );
  const button = () =>
    page.getByRole("button", { name: "Enviar mensagem", exact: true });
  const question = () => page.getByLabel("Sua pergunta", { exact: true });
  const pending = () => page.locator(".chat-pending");
  try {
    const initialRead = readResponse();
    await page.goto(`${base}/chat`);
    if (
      await page
        .getByLabel("E-mail", { exact: true })
        .isVisible()
        .catch(() => false)
    ) {
      await page.getByLabel("E-mail", { exact: true }).fill("admin@ares.local");
      await page.getByLabel("Senha", { exact: true }).fill("AresLocal!2026");
      await page.getByRole("button", { name: "Entrar", exact: true }).click();
    }
    await page
      .getByRole("heading", { name: "Chat ARES", exact: true })
      .waitFor();
    const realRead = await initialRead;
    assert.equal(realRead.status(), 200, "real unscoped history must load");
    assert.equal(new URL(realRead.url()).searchParams.has("scope_ref"), false);
    const realSnapshot = await realRead.json();
    assert.ok(Array.isArray(realSnapshot.items));
    if (realSnapshot.context)
      assert.ok(
        realSnapshot.context.tokens_upper_bound <=
          realSnapshot.context.token_limit,
      );
    assert.equal(await page.locator("#chat-scope").count(), 0);
    await question().waitFor();
    checks.push("Real local authentication and GET history without scope_ref");

    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);

    // All further chat requests are controlled fixtures; no model, CRM or DB mutation.
    let snapshot = { items: [], context: demoContext, model_available: true };
    let readStatus = 200,
      posts = 0,
      postHandler = null;
    await page.route(endpoint, async (route) => {
      if (route.request().method() === "GET")
        return route.fulfill({
          status: readStatus,
          json:
            readStatus === 200
              ? snapshot
              : {
                  error: {
                    code: readStatus === 403 ? "access_denied" : "chat_failed",
                    correlation_id: "synthetic-read-check",
                  },
                },
        });
      posts += 1;
      assert.ok(!route.request().postDataJSON().scope_ref);
      assert.ok(postHandler, "unexpected synthetic POST");
      return postHandler(route);
    });
    await page.reload();
    await question().waitFor();
    syntheticView = true;
    assert.equal(
      await page.locator(".chat-history > li.chat-welcome").count(),
      1,
    );
    assert.equal(
      await page
        .locator(".chat-context, .chat-exchange, .chat-speaker")
        .count(),
      0,
    );
    assert.equal(await button().isDisabled(), true);
    checks.push(
      "Empty unscoped conversation is usable without an opportunity selector",
    );

    const release = deferred(),
      received = deferred();
    postHandler = async (route) => {
      received.resolve();
      await release.promise;
      await route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          ["status", { phase: "searching", label: "Buscando oportunidades" }],
          ["tool", { name: "search_opportunities", status: "completed" }],
          ["context", demoContext],
          ["status", { phase: "writing", label: "Organizando a resposta" }],
          ["token", { text: markdown }],
          ["done", { id: "synthetic-comparison", status: "succeeded" }],
        ]),
      });
    };
    await question().fill("Compare as oportunidades");
    await question().press("Shift+Enter");
    assert.equal(await question().inputValue(), "Compare as oportunidades\n");
    assert.equal(posts, 0, "Shift+Enter inserts a line break");
    await question().fill("Compare as oportunidades de demonstração");
    await question().press("Enter");
    await received.promise;
    await pending().waitFor();
    await page
      .locator(".chat-message--user")
      .filter({ hasText: "Compare as oportunidades de demonstração" })
      .waitFor();
    assert.equal(
      await question().inputValue(),
      "",
      "composer clears as the message leaves it",
    );
    const messagePosition = await page.evaluate(() => {
      const bubble = document.querySelector(".chat-message--outgoing");
      const composer = document.querySelector(".chat-composer-box");
      return {
        gap:
          composer.getBoundingClientRect().top -
          bubble.getBoundingClientRect().bottom,
        animation: getComputedStyle(bubble).animationName,
      };
    });
    assert.ok(
      messagePosition.gap >= 0 && messagePosition.gap < 200,
      "sent message rises just above the composer",
    );
    assert.equal(
      messagePosition.animation,
      "none",
      "reduced motion disables the rise animation",
    );
    assert.equal(await button().isDisabled(), true);
    assert.equal(await question().isDisabled(), true);
    await page
      .locator(".chat-conversation form")
      .evaluate((form) => form.requestSubmit());
    assert.equal(posts, 1, "duplicate submission is blocked while pending");
    assert.equal(await pending().getAttribute("role"), "status");
    await page.emulateMedia({ reducedMotion: "no-preference" });
    assert.equal(await page.locator(".chat-typing-dot").count(), 3);
    const moving = await page
      .locator(".chat-typing-dot")
      .first()
      .evaluate((element) => {
        const style = getComputedStyle(element);
        return { name: style.animationName, duration: style.animationDuration };
      });
    assert.notEqual(moving.name, "none");
    assert.ok(parseFloat(moving.duration) >= 1.8);
    await page.emulateMedia({ reducedMotion: "reduce" });
    const reduced = await page
      .locator(".chat-typing-dot")
      .first()
      .evaluate((element) => {
        const style = getComputedStyle(element);
        return { name: style.animationName, duration: style.animationDuration };
      });
    assert.ok(
      reduced.name === "none" || parseFloat(reduced.duration) <= 0.001,
      "reduced motion stops the animation",
    );
    await page.screenshot({
      path: path.join(output, "chat-thinking-demo.png"),
      fullPage: true,
    });
    snapshot = {
      ...snapshot,
      items: [
        {
          id: "synthetic-comparison",
          user_text: "Compare as oportunidades de demonstração",
          assistant_text: markdown,
          status: "succeeded",
          context_json: demoContext,
          tool_calls_json: [
            { name: "search_opportunities", status: "completed" },
          ],
          created_at: "2026-09-26T12:00:00Z",
        },
      ],
    };
    await page.emulateMedia({ reducedMotion: "no-preference" });
    release.resolve();
    await page
      .locator(".chat-markdown")
      .filter({ hasText: "Comparativo de demonstração" })
      .waitFor();
    const partial = await page
      .locator(".chat-message--assistant")
      .last()
      .innerText();
    assert.ok(
      partial.length < markdown.length,
      "answer is revealed progressively",
    );
    await page.waitForFunction(
      () => !document.querySelector("#chat-text")?.disabled,
    );
    await page.locator(".chat-markdown table").waitFor();
    assert.equal(
      await page
        .locator(".chat-message--user")
        .filter({ hasText: "Compare as oportunidades de demonstração" })
        .count(),
      1,
    );
    assert.equal(
      await page.locator(".chat-markdown table tbody tr").count(),
      2,
    );
    assert.ok((await page.locator(".chat-markdown strong").count()) > 0);
    assert.ok((await page.locator(".chat-markdown ul li").count()) >= 2);
    assert.equal(
      await page.locator(".chat-markdown img, .chat-markdown script").count(),
      0,
    );
    assert.equal(
      await page
        .locator(
          '.chat-markdown a[href^="javascript:"], .chat-markdown a[href^="data:"]',
        )
        .count(),
      0,
    );
    assert.equal(
      await page.evaluate(() => Boolean(window.__chatUnsafeHtml)),
      false,
    );
    checks.push(
      "Enter submission, Shift+Enter newline, continuous conversation, progressive answer and three-dot pending state",
    );
    checks.push(
      "Reduced motion, Markdown tables/lists/bold/code, safe raw HTML and unsafe links",
    );

    // A long answer must open on the data, not on its final limitation note.
    const comparisonSnapshot = snapshot;
    const longAnswer = [
      "Estes são alguns registros disponíveis no seu acesso:",
      "",
      "| Oportunidade ou negócio | Etapa | Valor | Fonte |",
      "| --- | --- | ---: | --- |",
      ...Array.from(
        { length: 8 },
        (_, index) =>
          `| Demonstração ${index + 1} | proposta | BRL 12.500,00 | Banco ARES |`,
      ),
      "",
      "Este é um recorte da consulta, não o total do funil.",
      "",
      "**Limitação:** CRM indisponível nesta consulta.",
    ].join("\n");
    snapshot = {
      ...snapshot,
      items: [
        {
          id: "synthetic-long-answer",
          user_text: "Quais oportunidades temos hoje?",
          assistant_text: longAnswer,
          status: "succeeded",
          context_json: demoContext,
          tool_calls_json: [],
          created_at: "2026-09-26T12:00:00Z",
        },
      ],
    };
    await page.setViewportSize({ width: 1900, height: 837 });
    await page.reload();
    await page.locator(".chat-markdown table tbody tr").last().waitFor();
    await page.waitForFunction(() => {
      const history = document.querySelector(".chat-history");
      const reply = document.querySelector(".chat-message--assistant");
      return (
        history &&
        reply &&
        reply.getBoundingClientRect().top >=
          history.getBoundingClientRect().top - 15
      );
    });
    const readable = await page.evaluate(() => {
      const history = document.querySelector(".chat-history");
      const reply = document.querySelector(".chat-message--assistant");
      const table = reply.querySelector("table");
      const frame = history.getBoundingClientRect();
      return {
        visibleRows: [...table.querySelectorAll("tbody tr")].filter((row) => {
          const bounds = row.getBoundingClientRect();
          return bounds.bottom > frame.top && bounds.top < frame.bottom;
        }).length,
        headingHeight: document
          .querySelector(".chat-heading")
          .getBoundingClientRect().height,
        composerHeight: document
          .querySelector(".chat-composer")
          .getBoundingClientRect().height,
        historyHeight: frame.height,
        bodyScroll: document.documentElement.scrollHeight > innerHeight + 1,
      };
    });
    assert.ok(
      readable.visibleRows >= 6,
      "long answer opens with its data visible",
    );
    assert.ok(readable.headingHeight < 75 && readable.composerHeight < 110);
    assert.ok(readable.historyHeight > 450 && !readable.bodyScroll);
    await page.screenshot({
      path: path.join(output, "chat-data-demo.png"),
      fullPage: true,
    });
    if ((await page.locator("html").getAttribute("data-theme")) !== "dark") {
      await page
        .getByRole("button", { name: "Ativar modo escuro", exact: true })
        .click();
    }
    await page.screenshot({
      path: path.join(output, "chat-data-dark-demo.png"),
      fullPage: true,
    });
    const history = page.locator(".chat-history");
    const beforeKey = await history.evaluate((element) => element.scrollTop);
    await history.focus();
    await page.keyboard.press("PageDown");
    await page.waitForFunction(
      (previous) =>
        document.querySelector(".chat-history").scrollTop > previous,
      beforeKey,
    );
    await page.setViewportSize({ width: 390, height: 800 });
    await page.reload();
    await page.locator(".chat-markdown table tbody tr").last().waitFor();
    const mobileData = await page.evaluate(() => {
      const history = document.querySelector(".chat-history");
      const table = document.querySelector(".chat-table-scroll");
      const frame = history.getBoundingClientRect();
      return {
        visibleRows: [...table.querySelectorAll("tbody tr")].filter((row) => {
          const bounds = row.getBoundingClientRect();
          return bounds.bottom > frame.top && bounds.top < frame.bottom;
        }).length,
        horizontalTableScroll: table.scrollWidth > table.clientWidth,
        bodyOverflow: document.documentElement.scrollWidth > innerWidth + 1,
      };
    });
    assert.ok(mobileData.visibleRows >= 4);
    assert.ok(mobileData.horizontalTableScroll && !mobileData.bodyOverflow);
    assert.equal(await page.locator(".chat-table-hint").isVisible(), true);
    const mobileTable = page.locator(".chat-table-scroll");
    await mobileTable.focus();
    await page.keyboard.press("ArrowRight");
    await page.waitForFunction(
      () => document.querySelector(".chat-table-scroll").scrollLeft > 0,
    );
    await mobileTable.evaluate((element) => {
      element.scrollLeft = 0;
    });
    await page.screenshot({
      path: path.join(output, "chat-data-mobile-demo.png"),
      fullPage: true,
    });
    checks.push("Long data answer opens on its table in an 837 px viewport");
    snapshot = comparisonSnapshot;
    await page.reload();
    await page.locator(".chat-markdown table").waitFor();

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
    for (const theme of ["dark", "light"]) {
      if ((await page.locator("html").getAttribute("data-theme")) !== theme) {
        await page
          .getByRole("button", {
            name: theme === "dark" ? "Ativar modo escuro" : "Ativar modo claro",
            exact: true,
          })
          .click();
      }
      for (const width of [1920, 1440, 1280, 820, 390]) {
        await page.setViewportSize({ width, height: 1000 });
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
          `overflow ${theme}/${width}`,
        );
        const frame = await page.evaluate(() => {
          const page = document.querySelector(".chat-page");
          const history = document.querySelector(".chat-history");
          return {
            pageWidth: page.getBoundingClientRect().width,
            bodyScroll: document.documentElement.scrollHeight > innerHeight + 1,
            scrollbar: getComputedStyle(history).scrollbarWidth,
          };
        });
        assert.ok(
          frame.pageWidth > width * 0.82,
          `full-width chat ${theme}/${width}`,
        );
        assert.equal(
          frame.bodyScroll,
          false,
          `single viewport ${theme}/${width}`,
        );
        assert.equal(
          frame.scrollbar,
          "none",
          `hidden transcript scrollbar ${theme}/${width}`,
        );
        const violations = await page.evaluate(async () =>
          (
            await axe.run(".chat-page", {
              runOnly: {
                type: "tag",
                values: ["wcag2a", "wcag2aa", "wcag21aa"],
              },
            })
          ).violations.map((v) => ({
            id: v.id,
            targets: v.nodes.map((n) => ({
              target: n.target,
              html: n.html,
              summary: n.failureSummary,
            })),
          })),
        );
        assert.deepEqual(violations, [], `accessibility ${theme}/${width}`);
        await page.screenshot({
          path: path.join(output, `chat-${theme}-${width}.png`),
          fullPage: true,
        });
        layouts.push({ theme, width, violations, overflow: false });
      }
    }
    checks.push(
      "Axe and overflow checks in both themes at 1920/1440/1280/820/390 px",
    );

    await page.setViewportSize({ width: 1440, height: 1000 });
    snapshot = {
      ...snapshot,
      items: Array.from({ length: 40 }, (_, index) => ({
        id: `synthetic-history-${index}`,
        user_text: `Pergunta de demonstração ${index}`,
        assistant_text: `Resposta de demonstração ${index}.`,
        status: "succeeded",
        context_json: null,
        tool_calls_json: [],
        created_at: "2026-09-26T12:00:00Z",
      })),
    };
    await page.reload();
    await page.waitForFunction(
      () => document.querySelectorAll(".chat-message").length === 80,
    );
    const scrollable = await page
      .locator(".chat-history")
      .evaluate((history) => {
        history.scrollTop = 0;
        history.scrollTop = 200;
        return (
          history.scrollHeight > history.clientHeight && history.scrollTop > 0
        );
      });
    assert.equal(
      scrollable,
      true,
      "conversation still scrolls without a visible scrollbar",
    );
    snapshot = comparisonSnapshot;
    await page.reload();
    await page.locator(".chat-markdown table").waitFor();
    checks.push("Long conversations remain scrollable inside the viewport");

    postHandler = (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: sse([
          ["tool", { name: "search_opportunities", status: "completed" }],
          ["token", { text: "Resposta parcial de demonstração." }],
          [
            "error",
            {
              code: "model_response_failed",
              correlation_id: "synthetic-stream-check",
            },
          ],
        ]),
      });
    await question().fill("Verifique a falha de demonstração");
    await button().click();
    await page
      .getByRole("alert")
      .filter({ hasText: "synthetic-stream-check" })
      .waitFor();
    await page
      .getByText("Resposta parcial de demonstração.", { exact: true })
      .waitFor();
    assert.equal(await pending().count(), 0);
    assert.equal(await question().isDisabled(), false);
    checks.push(
      "Partial streamed answer retained with a visible error and correlation ID",
    );

    readStatus = 503;
    expectedHttpStatus = 503;
    await page.reload();
    await page
      .getByRole("alert")
      .filter({ hasText: "synthetic-read-check" })
      .waitFor();
    readStatus = 200;
    await page
      .getByRole("button", { name: "Tentar novamente", exact: true })
      .click();
    await question().waitFor();
    await page.locator(".chat-markdown table").waitFor();
    expectedHttpStatus = null;
    checks.push("History error has a working retry action");

    readStatus = 403;
    expectedHttpStatus = 403;
    const deniedResponse = readResponse();
    await page
      .getByRole("button", { name: "Atualizar conversa", exact: true })
      .click();
    await deniedResponse;
    await page
      .getByRole("alert")
      .filter({ hasText: "synthetic-read-check" })
      .waitFor();
    assert.equal(await question().count(), 0);
    assert.equal(
      await page.locator(".chat-message").count(),
      0,
      "denied state redacts cached messages",
    );
    expectedHttpStatus = null;
    checks.push("Access-denied state removes composer and cached conversation");
    readStatus = 200;
    await page.reload();
    await question().waitFor();
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);
    const report = {
      source:
        "Real local authentication and unscoped GET; synthetic fixtures afterward",
      realModelConfigured: realSnapshot.model_available,
      paidModelCalls: 0,
      checks,
      layouts,
      errors,
      consoleErrors,
      expectedConsoleErrors,
      screenshotData: "Only synthetic demonstration fixtures",
    };
    fs.writeFileSync(
      path.join(output, "report.json"),
      JSON.stringify(report, null, 2),
    );
    console.log(JSON.stringify(report));
  } catch (error) {
    if (syntheticView)
      await page.screenshot({
        path: path.join(output, "failure.png"),
        fullPage: true,
      });
    throw error;
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
