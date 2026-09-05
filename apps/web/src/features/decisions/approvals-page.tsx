import {
  CheckSquareOffsetIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  decideRecommendation,
  getApprovals,
} from "@/features/opportunities/api";
import { money } from "@/features/opportunities/format";
import { Button } from "@/components/ui/button";
import { Freshness } from "@/components/live/freshness";
import { LiveValue } from "@/components/live/live-value";

import { RecommendationCard } from "./recommendation-card";

export function ApprovalsPage() {
  const queryClient = useQueryClient();
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: getApprovals,
    refetchInterval: 4_000,
  });
  const decide = useMutation({
    mutationFn: ({
      id,
      command,
    }: {
      id: string;
      command: Parameters<typeof decideRecommendation>[1];
    }) => decideRecommendation(id, command),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["approvals"] });
      await queryClient.invalidateQueries({ queryKey: ["opportunity"] });
    },
  });

  return (
    <main className="workspace approvals-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ARES CONNECT / CONTROLE HUMANO</span>
          <h1>Fila de aprovações</h1>
          <p>
            Recomendações aguardam decisão explícita antes de qualquer escrita
            no CRM.
          </p>
          <Freshness timestamp={approvals.dataUpdatedAt} />
        </div>
        <div className="approval-count" aria-label="Aprovações pendentes">
          <CheckSquareOffsetIcon aria-hidden />
          <strong><LiveValue value={approvals.data?.total ?? 0} /></strong>
          <span>pendentes</span>
        </div>
      </header>

      {decide.isError && (
        <div className="conflict-banner" role="alert">
          <WarningCircleIcon aria-hidden />
          <div>
            <strong>Decisão não aplicada</strong>
            <span>
              {decide.error.message === "stale_recommendation"
                ? "Outra pessoa alterou esta recomendação. A fila foi atualizada."
                : decide.error.message}
            </span>
          </div>
        </div>
      )}

      {approvals.isLoading ? (
        <div
          className="approval-grid approval-loading"
          aria-label="Carregando aprovações"
        >
          <i />
          <i />
        </div>
      ) : approvals.isError && !approvals.data ? (
        <div className="empty-state" role="alert">
          <strong>Fila indisponível</strong>
          <span>{approvals.error.message}</span>
          <Button variant="outline" onClick={() => void approvals.refetch()}>Tentar novamente</Button>
        </div>
      ) : approvals.data?.items.length ? (
        <section className="approval-grid" aria-label="Recomendações pendentes">
          {approvals.data.items.map((item) => (
            <div className="approval-item" key={item.id}>
              <div className="approval-context">
                <div>
                  <span>Oportunidade em risco</span>
                  <Link to={`/opportunities/${item.opportunity_id}`}>
                    {item.title}
                  </Link>
                </div>
                <strong>{money(item.deal_value, item.currency)}</strong>
              </div>
              <RecommendationCard
                recommendation={item}
                compact
                pending={decide.isPending}
                onDecide={(command) => decide.mutate({ id: item.id, command })}
              />
            </div>
          ))}
        </section>
      ) : (
        <div className="empty-state approval-empty">
          <CheckSquareOffsetIcon aria-hidden />
          <strong>Nenhuma decisão pendente</strong>
          <span>
            Gere uma recomendação no detalhe de uma oportunidade do Radar.
          </span>
          <Link to="/radar">Abrir Radar ARES</Link>
        </div>
      )}
    </main>
  );
}
