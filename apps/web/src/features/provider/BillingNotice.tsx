import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/lib/supabase";
export function BillingNotice() {
  const query = useQuery({
    queryKey: ["account-billing"],
    queryFn: async () => {
      const { data } = await supabase.auth.getSession();
      const result = await fetch(
        `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/account/billing`,
        {
          headers: {
            Authorization: `Bearer ${data.session?.access_token ?? ""}`,
          },
        },
      );
      if (!result.ok)
        throw new Error("Não foi possível verificar o estado de cobrança.");
      return result.json() as Promise<{
        state: string;
        degraded: boolean;
        grace_until?: string | null;
      }>;
    },
    refetchInterval: 60000,
    retry: false,
  });
  if (query.error)
    return (
      <p role="status" className="workspace">
        Estado de cobrança indisponível. As ações continuam sendo verificadas
        pelo servidor.
      </p>
    );
  if (!query.data || !["past_due", "degraded"].includes(query.data.state))
    return null;
  return (
    <p role="status" className="workspace">
      {query.data.degraded
        ? "Prazo de pagamento encerrado. Escrita e IA suspensas; leitura e histórico disponíveis."
        : `Pagamento pendente. Regularize até ${query.data.grace_until ?? "o prazo contratual"}. O produto permanece disponível.`}
    </p>
  );
}
