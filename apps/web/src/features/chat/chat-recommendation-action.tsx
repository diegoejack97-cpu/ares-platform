import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/auth-context";
import { getCommercialConfiguration } from "@/features/agents/commercial-api";
import {
  getOpportunity,
  generateRecommendation,
} from "@/features/opportunities/api";

export function ChatRecommendationAction({
  opportunity,
}: {
  opportunity: string;
}) {
  const { session } = useAuth();
  const client = useQueryClient();
  const config = useQuery({
    queryKey: [
      "commercial-config",
      session.user.id,
      session.user.app_metadata.active_tenant_id,
    ],
    queryFn: getCommercialConfiguration,
  });
  const detail = useQuery({
    queryKey: ["chat-recommendation", session.user.id, opportunity],
    queryFn: () => getOpportunity(opportunity),
    enabled: !!config.data?.config?.recommendations_enabled,
    refetchInterval: 5000,
  });
  const mutation = useMutation({
    mutationFn: () => generateRecommendation(opportunity),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["chat-recommendation"] }),
  });
  if (!config.data?.config?.recommendations_enabled || !detail.data)
    return null;
  const recommendation = detail.data.recommendation;
  return (
    <div className="chat-specialist-action">
      {recommendation ? (
        <>
          <span>
            Proposta: {recommendation.status}. Executada somente após recibo
            confirmado.
          </span>
          <Link to={`/opportunities/${opportunity}`}>
            Abrir proposta e aprovação
          </Link>
        </>
      ) : detail.data.can_request_recommendation ? (
        <Button
          variant="outline"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending
            ? "Preparando proposta…"
            : "Preparar recomendação"}
        </Button>
      ) : (
        <span>Proposta indisponível para o estado atual.</span>
      )}
      {mutation.isError ? (
        <p role="alert">
          Não foi possível preparar a proposta: {mutation.error.message}
        </p>
      ) : null}
      <small>A conversa não aprova nem executa ações.</small>
    </div>
  );
}
