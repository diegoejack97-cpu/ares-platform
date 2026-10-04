import { supabase } from "@/lib/supabase";
import type { ChatHistory } from "@/features/agents/contract";

const base = `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/chat/messages`;
export class ChatError extends Error {
  status: number;
  code: string;
  correlationId?: string;
  constructor(status: number, code: string, correlationId?: string) {
    super(
      code === "ai_budget_exceeded"
        ? "Limite de IA atingido. Revise a cota antes de enviar."
        : code === "chat_busy"
          ? "Há uma resposta em andamento nesta conversa. Atualize a leitura."
          : status === 404 || status === 403
            ? "Chat indisponível neste acesso."
            : "Não foi possível concluir a consulta. Tente novamente.",
    );
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }
}
async function headers() {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new ChatError(401, "session_expired");
  return {
    Authorization: `Bearer ${data.session.access_token}`,
    "Content-Type": "application/json",
  };
}
async function check(response: Response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ChatError(
      response.status,
      body.error?.code ?? "chat_failed",
      body.error?.correlation_id,
    );
  }
}
export async function getChat(
  scope?: string,
  signal?: AbortSignal,
): Promise<ChatHistory> {
  const response = await fetch(
    scope ? `${base}?scope_ref=${encodeURIComponent(scope)}` : base,
    { headers: await headers(), signal },
  );
  await check(response);
  return response.json();
}
export async function sendChat(
  scope: string | undefined,
  text: string,
  signal: AbortSignal,
  receive: (event: string, data: Record<string, unknown>) => void,
) {
  const response = await fetch(base, {
    method: "POST",
    headers: await headers(),
    signal,
    body: JSON.stringify(scope ? { text, scope_ref: scope } : { text }),
  });
  await check(response);
  if (!response.body) throw new ChatError(503, "stream_missing");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    doneSeen = false;
  try {
    while (true) {
      const result = await reader.read();
      buffer += decoder
        .decode(result.value, { stream: !result.done })
        .replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const lines = block.split("\n");
        const event = lines
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const raw = lines
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (!event || !raw) continue;
        const data = JSON.parse(raw) as Record<string, unknown>;
        if (event === "error")
          throw new ChatError(
            503,
            String(data.code),
            String(data.correlation_id),
          );
        if (event === "done") doneSeen = true;
        receive(event, data);
      }
      if (result.done) break;
    }
    if (!doneSeen) throw new ChatError(503, "stream_interrupted");
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}
