import type { Tone } from "@/components/console";

export const money = (
  amount: string | number | null,
  currency: string | null,
) =>
  amount === null
    ? null
    : `${currency ?? "Moeda ausente"} ${Number(amount).toLocaleString("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
export const compact = (value: number) =>
  value.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
export const when = (value: string | null) =>
  value ? new Date(value).toLocaleDateString("pt-BR") : null;

export const interventionStatus: Record<string, { tone: Tone; label: string }> =
  {
    open: { tone: "warning", label: "Aberta" },
    deciding: { tone: "warning", label: "Em decisão" },
    executing: { tone: "info", label: "Executando" },
    observing: { tone: "info", label: "Observando" },
    closed: { tone: "neutral", label: "Encerrada" },
    cancelled: { tone: "neutral", label: "Cancelada" },
  };
export const resultLabels: Record<string, string> = {
  sale_observed: "Venda observada",
  recovered: "Recuperada",
  action_executed: "Ação executada",
};
export const attributionLabels: Record<string, string> = {
  observed: "observado",
  associated: "associado",
  influenced: "influenciado",
  incremental_proven: "incremental comprovado",
};
