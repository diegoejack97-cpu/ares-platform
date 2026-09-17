import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import type {
  LicensePage as LicenseData,
  InviteCommand,
} from "@/features/agents/contract";
import "./provider.css";

async function account<T>(path: string, body?: unknown): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/account${path}`,
    {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${data.session?.access_token ?? ""}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      `Operação não concluída: ${error?.detail?.code ?? response.status}. Correlação: ${error?.detail?.correlation_id ?? "não informada"}.`,
    );
  }
  return response.json();
}
const schema = z.object({
  email: z.string().email(),
  role: z.enum(["admin", "manager", "seller", "auditor"]),
  reason: z.string().min(3).max(500),
});
export function LicensePage() {
  const client = useQueryClient();
  const [invitationCursor, setInvitationCursor] = useState<string | null>(null);
  const [memberCursor, setMemberCursor] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [accountId, setAccountId] = useState("");
  const form = useForm<InviteCommand>({
    resolver: zodResolver(schema),
    defaultValues: { role: "seller" },
  });
  const query = useQuery({
    queryKey: ["licenses", invitationCursor, memberCursor],
    queryFn: () =>
      account<LicenseData>(
        `/licenses?${new URLSearchParams({ ...(invitationCursor ? { invitation_cursor: invitationCursor } : {}), ...(memberCursor ? { member_cursor: memberCursor } : {}) })}`,
      ),
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) =>
      account(path, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["licenses"] });
    },
  });
  return (
    <main className="workspace provider-page">
      <header className="page-heading">
        <span className="eyebrow">ADMINISTRAÇÃO DO TENANT</span>
        <h1>Licenças e convites</h1>
        <p>
          Convites pendentes reservam uma licença. O limite é verificado no
          convite e na ativação.
        </p>
      </header>
      {query.isPending && <p role="status">Carregando licenças…</p>}
      {query.error && <p role="alert">{query.error.message}</p>}
      <Button
        variant="outline"
        onClick={() => {
          void query.refetch();
        }}
      >
        Atualizar licenças
      </Button>
      {query.data && (
        <>
          <p role="status">
            {query.data.used} de {query.data.seats_limit} licenças ocupadas ou
            reservadas.
          </p>
          <form
            className="provider-form"
            onSubmit={form.handleSubmit((body) =>
              mutation.mutate({ path: "/invitations", body }),
            )}
          >
            <h2>Registrar convite</h2>
            <p>
              O registro não envia e-mail. A ativação exige uma conta com e-mail
              verificado.
            </p>
            <label>
              E-mail
              <input type="email" {...form.register("email")} />
            </label>
            <label>
              Papel
              <select {...form.register("role")}>
                <option value="seller">Vendedor</option>
                <option value="manager">Gestor</option>
                <option value="auditor">Auditor</option>
                <option value="admin">Administrador</option>
              </select>
            </label>
            <label>
              Justificativa do convite
              <input {...form.register("reason")} />
            </label>
            {Object.values(form.formState.errors).map((error, i) => (
              <p role="alert" key={i}>
                {error.message}
              </p>
            ))}
            <Button
              disabled={
                mutation.isPending || query.data.used >= query.data.seats_limit
              }
            >
              Registrar convite
            </Button>
          </form>
          <section className="panel provider-form">
            <h2>Revisar acesso</h2>
            <label>
              Justificativa da alteração
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
              />
            </label>
            <label>
              ID da conta verificada para ativação
              <input
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
              />
            </label>
            <h3>Convites</h3>
            {!query.data.invitations.length && (
              <p>Nenhum convite nesta página.</p>
            )}
            <ul>
              {query.data.invitations.map((item) => (
                <li key={item.id}>
                  <p>
                    {item.email} · {item.role} · {item.status}
                  </p>
                  {item.status === "pending" && (
                    <>
                      <Button
                        disabled={
                          mutation.isPending ||
                          reason.trim().length < 3 ||
                          !z.string().uuid().safeParse(accountId).success
                        }
                        onClick={() =>
                          mutation.mutate({
                            path: `/invitations/${item.id}/activate`,
                            body: {
                              expected_version: item.version,
                              user_id: accountId,
                              reason,
                            },
                          })
                        }
                      >
                        Ativar {item.email}
                      </Button>
                      <Button
                        variant="outline"
                        disabled={
                          mutation.isPending || reason.trim().length < 3
                        }
                        onClick={() =>
                          mutation.mutate({
                            path: `/invitations/${item.id}/cancel`,
                            body: {
                              expected_version: item.version,
                              active: false,
                              reason,
                            },
                          })
                        }
                      >
                        Cancelar {item.email}
                      </Button>
                    </>
                  )}
                </li>
              ))}
            </ul>
            {query.data.next_invitation && (
              <Button
                onClick={() => setInvitationCursor(query.data!.next_invitation)}
              >
                Próximos convites
              </Button>
            )}
            <h3>Membros</h3>
            <ul>
              {query.data.memberships.map((item) => (
                <li key={item.user_id}>
                  <p>
                    {item.user_id} · {item.role} ·{" "}
                    {item.active ? "Ativo" : "Inativo"}
                  </p>
                  <Button
                    variant="outline"
                    disabled={mutation.isPending || reason.trim().length < 3}
                    onClick={() =>
                      mutation.mutate({
                        path: `/memberships/${item.user_id}`,
                        body: {
                          expected_version: item.version,
                          active: !item.active,
                          reason,
                        },
                      })
                    }
                  >
                    {item.active ? "Desativar" : "Reativar"} {item.user_id}
                  </Button>
                </li>
              ))}
            </ul>
            {query.data.next_member && (
              <Button onClick={() => setMemberCursor(query.data!.next_member)}>
                Próximos membros
              </Button>
            )}
            {(invitationCursor || memberCursor) && (
              <Button
                onClick={() => {
                  setMemberCursor(null);
                  setInvitationCursor(null);
                }}
              >
                Primeira página
              </Button>
            )}
          </section>
        </>
      )}
      {mutation.isPending && <p role="status">Salvando alteração auditada…</p>}
      {mutation.isSuccess && <p role="status">Alteração registrada.</p>}
      {mutation.error && (
        <p role="alert">
          {mutation.error.message} Atualize os dados e tente novamente.
        </p>
      )}
    </main>
  );
}

export function QuotaNotice() {
  const query = useQuery({
    queryKey: ["account-quota"],
    queryFn: () =>
      account<{
        configured: boolean;
        warning?: boolean;
        daily?: string;
        monthly?: string;
        ai_daily_budget_brl?: string;
        ai_monthly_budget_brl?: string;
      }>("/quota"),
    refetchInterval: 60000,
    retry: false,
  });
  if (query.error)
    return (
      <p role="status" className="workspace">
        Consumo de IA indisponível. O servidor verifica o limite antes de cada
        execução.
      </p>
    );
  if (!query.data) return null;
  if (!query.data.configured)
    return (
      <p role="status" className="workspace">
        Cota de IA ainda não configurada pelo provedor. Novas execuções de IA
        estão bloqueadas.
      </p>
    );
  if (Number(query.data.ai_daily_budget_brl) <= 0)
    return (
      <p role="status" className="workspace">
        Cota de IA zerada pelo provedor. Execuções de IA estão bloqueadas;
        leitura e histórico continuam disponíveis.
      </p>
    );
  if (!query.data.warning) return null;
  return (
    <p role="status" className="workspace">
      Atenção à cota de IA: consumo e reservas atingiram pelo menos 80% do
      limite. Consumo medido: R$ {query.data.daily} hoje e R${" "}
      {query.data.monthly} no mês. Limites: R$ {query.data.ai_daily_budget_brl}
      /dia e R$ {query.data.ai_monthly_budget_brl}/mês.
    </p>
  );
}
