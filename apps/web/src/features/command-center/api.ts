import { supabase } from "@/lib/supabase";
import type { CommandCenterSummary } from "@/features/agents/contract";

export class CommandCenterError extends Error {
  status: number;
  code: string;
  correlationId: string | null;
  constructor(
    status: number,
    code: string,
    message: string,
    correlationId: string | null = null,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }
}

const UNAVAILABLE =
  "Não foi possível consultar o Command Center. Tente novamente.";

export async function commandCenter(
  days: number,
  signal?: AbortSignal,
): Promise<CommandCenterSummary> {
  const { data } = await supabase.auth.getSession();
  if (!data.session)
    throw new CommandCenterError(401, "session_expired", "Sessão expirada.");
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/command-center?days=${days}`,
    {
      signal,
      headers: { Authorization: `Bearer ${data.session.access_token}` },
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = body?.error ?? {};
    if (response.status === 403 || response.status === 404)
      throw new CommandCenterError(
        response.status,
        "access_denied",
        "Esta conta não tem acesso ao Command Center.",
        error.correlation_id ?? null,
      );
    throw new CommandCenterError(
      response.status,
      error.code ?? "command_center_unavailable",
      error.message ?? UNAVAILABLE,
      error.correlation_id ?? null,
    );
  }
  return response.json();
}
