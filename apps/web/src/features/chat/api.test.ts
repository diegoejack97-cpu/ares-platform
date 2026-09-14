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
