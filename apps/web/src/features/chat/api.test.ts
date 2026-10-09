import { afterEach, expect, test, vi } from "vitest";
import { sendChat } from "./api";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({
        data: { session: { access_token: "synthetic" } },
      }),
    },
  },
}));
afterEach(() => vi.unstubAllGlobals());

function response(text: string) {
  const bytes = new TextEncoder().encode(text);
  // Split inside UTF-8 and SSE delimiters, as a real network can.
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );
}
test("SSE preserves accented text across fragments and requires completion", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      response(
        'event: token\ndata: {"text":"ação"}\n\nevent: done\ndata: {}\n\n',
      ),
    ),
  );
  const events: string[] = [];
  await sendChat(
    "scope",
    "question",
    new AbortController().signal,
    (kind, data) => events.push(`${kind}:${data.text ?? ""}`),
  );
  expect(events).toEqual(["token:ação", "done:"]);
});
test("an abruptly closed response is not reported as complete", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response('event: token\ndata: {"text":"partial"}\n\n')),
  );
  await expect(
    sendChat("scope", "question", new AbortController().signal, () => {}),
  ).rejects.toMatchObject({ code: "stream_interrupted" });
});

test("request rate limit explains the wait and preserves correlation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "request_rate_limited",
              correlation_id: "synthetic-correlation",
            },
          }),
          {
            status: 429,
            headers: {
              "Content-Type": "application/json",
              "Retry-After": "17",
            },
          },
        ),
    ),
  );
  await expect(
    sendChat(undefined, "question", new AbortController().signal, () => {}),
  ).rejects.toMatchObject({
    status: 429,
    code: "request_rate_limited",
    correlationId: "synthetic-correlation",
    message: expect.stringContaining("17 segundos"),
  });
});
