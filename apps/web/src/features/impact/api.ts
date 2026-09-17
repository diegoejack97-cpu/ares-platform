import { supabase } from "@/lib/supabase";
import type { ImpactSummary, ImpactPage } from "@/features/agents/contract";
async function response(path: string, signal?: AbortSignal) {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Sessão expirada. Entre novamente.");
  const result = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1${path}`,
    {
      signal,
      headers: { Authorization: `Bearer ${data.session.access_token}` },
    },
  );
  if (!result.ok)
    throw new Error(
      result.status === 403
        ? "Esta conta não tem acesso a este relatório."
        : "Não foi possível consultar Impacto ARES. Tente novamente.",
    );
  return result;
}
export async function impactSummary(
  days: number,
  signal?: AbortSignal,
): Promise<ImpactSummary> {
  return (await response(`/impact/summary?days=${days}`, signal)).json();
}
export async function impactPage(
  days: number,
  cursor: string | null,
  signal?: AbortSignal,
): Promise<ImpactPage> {
  return (
    await response(
      `/impact/interventions?days=${days}${cursor ? `&cursor=${cursor}` : ""}`,
      signal,
    )
  ).json();
}
export async function downloadImpact(days: number, format: "csv" | "pdf") {
  let result = await response(
    `/reports/impact/export?days=${days}&format=${format}`,
  );
  if (result.status === 202) {
    const job = (await result.json()) as { download_path: string };
    for (let attempt = 0; attempt < 120 && result.status === 202; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      result = await response(job.download_path);
    }
    if (result.status === 202)
      throw new Error(
        "Relatório ainda em processamento. Tente novamente em instantes.",
      );
  }
  const blob = await result.blob();
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = `ares-impacto.${format}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
