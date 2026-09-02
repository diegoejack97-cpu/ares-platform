export const signalLabels: Record<string, string> = {
  follow_up_overdue: "Follow-up vencido",
  proposal_stalled: "Proposta parada",
  missing_next_step: "Próximo passo ausente",
  unowned_deal: "Negócio sem responsável",
  high_value_at_risk: "Alto valor em risco",
  contact_inactive: "Contato inativo",
  close_date_at_risk: "Fechamento em risco",
  stage_regression: "Regressão de estágio",
};

export function money(value: number, currency = "BRL") {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency }).format(
    value,
  );
}

export function dateTime(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function slaLabel(value: string | null, now = Date.now()) {
  if (!value) return "Sem SLA";
  const diff = new Date(value).getTime() - now;
  const overdue = diff < 0;
  const minutes = Math.max(1, Math.round(Math.abs(diff) / 60_000));
  const amount =
    minutes >= 60
      ? `${Math.floor(minutes / 60)}h ${minutes % 60}min`
      : `${minutes}min`;
  return overdue ? `${amount} vencido` : `${amount} restante`;
}
