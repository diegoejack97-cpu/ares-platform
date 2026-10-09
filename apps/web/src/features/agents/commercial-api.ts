import { supabase } from "@/lib/supabase";
import type {
  CommercialConfig,
  PortfolioRequest,
  PortfolioView,
} from "./contract";

export type CommercialConfiguration = {
  version: number;
  can_configure: boolean;
  available: boolean;
  config: null | {
    enabled: boolean;
    recommendations_enabled: boolean;
    proactive_enabled: boolean;
    criterion: PortfolioRequest["criterion"];
    currency: string | null;
    cooldown_hours: number;
    daily_proposal_limit: number;
    calendar_json: CommercialConfig["calendar"];
  };
};

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Sessão ausente.");
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/agents/commercial/${path}`,
    {
      method,
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      `Operação indisponível: ${detail?.error?.code ?? response.status}`,
    );
  }
  return response.json() as Promise<T>;
}

export const getCommercialConfiguration = () =>
  request<CommercialConfiguration>("configuration");
export const saveCommercialConfiguration = (command: CommercialConfig) =>
  request<CommercialConfiguration>("configuration", "PUT", command);
export const getPortfolioAnalysis = (command: PortfolioRequest) => {
  const query = new URLSearchParams({
    criterion: command.criterion ?? "urgency",
  });
  if (command.currency) query.set("currency", command.currency);
  return request<PortfolioView>(`portfolio?${query}`);
};
export const startPortfolioAnalysis = (command: PortfolioRequest) =>
  request<{ id: string; reused: boolean }>("portfolio", "POST", command);
