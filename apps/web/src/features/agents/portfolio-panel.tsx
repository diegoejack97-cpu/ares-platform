import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/auth-context";
import type { PortfolioRequest } from "./contract";
import { getPortfolioAnalysis, startPortfolioAnalysis } from "./commercial-api";
import "./commercial.css";

const labels = {
  urgency: "Urgência de intervenção",
  value: "Maior valor",
  deadline: "Prazo mais próximo",
  attractiveness: "Atratividade com evidências",
};
export function PortfolioPanel() {
  const { session } = useAuth();
  const client = useQueryClient();
  const [criterion, setCriterion] =
    useState<NonNullable<PortfolioRequest["criterion"]>>("urgency");
  const [currency, setCurrency] = useState("BRL");
  const command = {
    criterion,
    currency: criterion === "value" ? currency : null,
  };
  const key = [
    "portfolio-analysis",
    session.user.id,
    session.user.app_metadata.active_tenant_id,
    criterion,
    command.currency,
  ];
  const query = useQuery({
    queryKey: key,
    queryFn: () => getPortfolioAnalysis(command),
    refetchInterval: (q) =>
      ["queued", "running"].includes(q.state.data?.state ?? "") ? 3000 : 30000,
  });
  const mutation = useMutation({
    mutationFn: () => startPortfolioAnalysis(command),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["portfolio-analysis"] }),
  });
  const data = query.data;
  const pending =
    mutation.isPending || ["queued", "running"].includes(data?.state ?? "");
  return (
    <section
      className="panel commercial-panel"
      aria-label="Leitura comercial da carteira"
    >
      <header>
        <div>
          <span className="eyebrow">LEITURA DA CARTEIRA</span>
          <h2>Onde agir agora</h2>
          <p>Interpretação separada do score e da prioridade do Core.</p>
        </div>
        <div className="commercial-controls">
          <label>
            Critério
            <select
              value={criterion}
              onChange={(e) => setCriterion(e.target.value as typeof criterion)}
            >
              {Object.entries(labels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {criterion === "value" ? (
            <label>
              Moeda
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
              >
                {["BRL", "USD", "EUR"].map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
          ) : null}
          <Button
            disabled={!data?.can_request || pending}
            onClick={() => mutation.mutate()}
          >
            {pending ? "Analisando carteira…" : "Analisar carteira"}
          </Button>
        </div>
      </header>
      {query.isPending ? (
        <p role="status">Carregando leitura autorizada…</p>
      ) : null}
      {query.isError || mutation.isError ? (
        <p role="alert">
          Não foi possível atualizar a análise.{" "}
          <Button variant="outline" onClick={() => void query.refetch()}>
            Tentar novamente
          </Button>{" "}
          {mutation.error?.message}
        </p>
      ) : null}
      {data ? (
        <>
          <p>
            {data.source} ·{" "}
            {data.scope === "own_portfolio" ? "Sua carteira" : "Empresa"} ·{" "}
            {data.total} negócios no recorte ·{" "}
            {data.created_at
              ? new Date(data.created_at).toLocaleString("pt-BR")
              : "Sem análise gerada"}
          </p>
          <p>
            {data.coverage_note}{" "}
            {data.state === "degraded"
              ? "Resultado de fallback; interpretação por IA indisponível."
              : data.state === "stale"
                ? "Análise anterior desatualizada. Gere uma nova leitura."
                : data.state === "failed"
                  ? "Análise interrompida; o Radar permanece disponível."
                  : null}
          </p>
          <ul
            className="commercial-currency-totals"
            aria-label="Valores por moeda"
          >
            {data.currency_totals.map((group) => (
              <li key={group.currency ?? "unknown"}>
                <strong>{group.currency ?? "Moeda não informada"}</strong>{" "}
                {group.value == null
                  ? "Valor não informado"
                  : Number(group.value).toLocaleString("pt-BR", {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                {" · "}
                {group.records} negócios
              </li>
            ))}
          </ul>
          {!data.can_request ? (
            <p>
              Ative a rotina comercial em Agentes, conforme a capacidade do
              plano.
            </p>
          ) : null}
          {data.briefing ? (
            <div className="commercial-briefing">
              <strong>{data.briefing.summary}</strong>
              <ul>
                {[
                  ...data.briefing.risks,
                  ...data.briefing.next_steps,
                  ...data.briefing.limitations,
                ].map((text, index) => (
                  <li key={index}>{text}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <ol className="commercial-ranking">
            {data.ranking?.ranking.map((item) => (
              <li key={item.opportunity_id}>
                <Link to={`/opportunities/${item.opportunity_id}`}>
                  {data.candidates.find(
                    (candidate) => candidate.id === item.opportunity_id,
                  )?.title ?? "Abrir oportunidade"}
                </Link>
                <p>{item.reason}</p>
                <p>
                  {data.candidates.find(
                    (candidate) => candidate.id === item.opportunity_id,
                  )?.currency ?? "Moeda não informada"}
                  {" · "}
                  {(() => {
                    const candidate = data.candidates.find(
                      (entry) => entry.id === item.opportunity_id,
                    );
                    return candidate?.value == null
                      ? "Valor não informado"
                      : Number(candidate.value).toLocaleString("pt-BR", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        });
                  })()}
                </p>
                <Link to={`/chat?scope=${item.opportunity_id}`}>
                  Explicar no chat
                </Link>
              </li>
            ))}
          </ol>
          {!data.total ? (
            <p>Nenhum negócio aberto no recorte autorizado.</p>
          ) : null}
          <footer>
            Período: retrato atual · Valores por moeda, sem conversão ·
            Validade:{" "}
            {data.valid_until
              ? new Date(data.valid_until).toLocaleString("pt-BR")
              : "não gerada"}{" "}
            · {data.run_ids.length} etapas registradas
          </footer>
        </>
      ) : null}
    </section>
  );
}
