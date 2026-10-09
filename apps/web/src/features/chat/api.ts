import { supabase } from "@/lib/supabase";
import type { ChatHistory } from "@/features/agents/contract";

const base = `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/chat/messages`;
export class ChatError extends Error {
  status: number;
  code: string;
  correlationId?: string;
  constructor(
    status: number,
    code: string,
    correlationId?: string,
    retryAfter?: number,
  ) {
    super(
      code === "request_rate_limited"
        ? `Muitas mensagens ou solicitações. Aguarde ${retryAfter ?? 60} segundos antes de tentar novamente.`
        : code === "ai_budget_exceeded"
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
      body.error?.code ?? body.detail?.code ?? "chat_failed",
      body.error?.correlation_id ?? body.detail?.correlation_id,
      Number(response.headers.get("Retry-After")) || undefined,
    );
  }
}
export async function getChat(
  scope?: string,
  signal?: AbortSignal,
  finding?: string,
  before?: string,
): Promise<ChatHistory> {
  const params = new URLSearchParams();
  if (finding) params.set("finding_ref", finding);
  else if (scope) params.set("scope_ref", scope);
  if (before) params.set("before", before);
  const response = await fetch(`${base}?${params}`, {
    headers: await headers(),
    signal,
  });
  await check(response);
  return response.json();
}
export async function sendChat(
  scope: string | undefined,
  text: string,
  signal: AbortSignal,
  receive: (event: string, data: Record<string, unknown>) => void,
  finding?: string,
) {
  const response = await fetch(base, {
    method: "POST",
    headers: await headers(),
    signal,
    body: JSON.stringify(
      finding
        ? { text, finding_ref: finding }
        : scope
          ? { text, scope_ref: scope }
          : { text },
    ),
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

export async function openFindingChat(finding: string, signal?: AbortSignal) {
  const response = await fetch(
    `${base.replace("/messages", "")}/findings/${encodeURIComponent(finding)}/open`,
    { method: "POST", headers: await headers(), signal },
  );
  await check(response);
  return response.json();
}
export async function saveChatFeedback(
  message: string,
  rating: "helpful" | "unhelpful",
  reason: string,
) {
  const response = await fetch(
    `${base}/${encodeURIComponent(message)}/feedback`,
    {
      method: "PUT",
      headers: await headers(),
      body: JSON.stringify({ rating, reason }),
    },
  );
  await check(response);
  return response.json();
}
