import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowsClockwiseIcon, UserPlusIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Meter,
  NoticeBar,
  StatusBadge,
  roleLabels,
} from "@/components/console";
import type {
  InvitationRecord,
  LicensePage as LicenseData,
  MembershipRecord,
} from "@/features/agents/contract";
import { account } from "./account-api";
import "./provider.css";

export { QuotaNotice } from "./BillingNotice";

const schema = z.object({
  email: z.email("Informe um e-mail válido."),
  role: z.enum(["admin", "manager", "seller", "auditor"]),
  reason: z
    .string()
    .trim()
    .min(3, "Informe a justificativa (mínimo 3 caracteres).")
    .max(500),
});
type InviteForm = z.infer<typeof schema>;

const invitationTone = {
  pending: ["warning", "Pendente"],
  accepted: ["good", "Ativado"],
  cancelled: ["neutral", "Cancelado"],
} as const;

type Drawer =
  | { kind: "activate" | "cancel"; invitation: InvitationRecord }
  | { kind: "member"; member: MembershipRecord };

export function LicensePage() {
  const client = useQueryClient();
  const [invitationCursor, setInvitationCursor] = useState<string | null>(null);
  const [memberCursor, setMemberCursor] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer | null>(null);
  const [reason, setReason] = useState("");
  const [accountId, setAccountId] = useState("");
  const form = useForm<InviteForm>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", role: "seller", reason: "" },
  });
  const query = useQuery({
    queryKey: ["licenses", invitationCursor, memberCursor],
    queryFn: () =>
      account<LicenseData>(
        `/licenses?${new URLSearchParams({
          ...(invitationCursor ? { invitation_cursor: invitationCursor } : {}),
          ...(memberCursor ? { member_cursor: memberCursor } : {}),
        })}`,
      ),
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) =>
      account(path, body),
    onSuccess: () => {
      setDrawer(null);
      setReason("");
      setAccountId("");
      void client.invalidateQueries({ queryKey: ["licenses"] });
    },
  });
  const invite = useMutation({
    mutationFn: (body: InviteForm) => account("/invitations", body),
    onSuccess: () => {
      form.reset();
      void client.invalidateQueries({ queryKey: ["licenses"] });
    },
  });
  const open = (next: Drawer) => {
    setDrawer(next);
    setReason("");
    setAccountId("");
    mutation.reset();
  };
  const data = query.data;
  const available = data ? Math.max(data.seats_limit - data.used, 0) : 0;
  const full = data ? data.used >= data.seats_limit : false;
  const pendingCount = data
    ? data.invitations.filter((item) => item.status === "pending").length
    : 0;
  const reasonReady = reason.trim().length >= 3;
  const accountReady = z.uuid().safeParse(accountId).success;

  const drawerForm = (title: string, confirm: string, extra?: ReactNode) => (
    <tr className="row-drawer">
      <td colSpan={4}>
        <h4>{title}</h4>
        <div className="form-grid is-inline">
          <div className="field">
            <label htmlFor="license-reason">Justificativa da alteração</label>
            <Input
              id="license-reason"
              value={reason}
              maxLength={500}
              autoFocus
              onChange={(event) => setReason(event.target.value)}
            />
          </div>
          {extra}
          <div className="form-actions">
            <Button
              disabled={
                mutation.isPending ||
                !reasonReady ||
                (drawer?.kind === "activate" && !accountReady)
              }
              onClick={() => drawer && submit(drawer)}
            >
              {confirm}
            </Button>
            <Button variant="outline" onClick={() => setDrawer(null)}>
              Voltar
            </Button>
          </div>
        </div>
        {mutation.error ? (
          <p className="inline-alert" role="alert">
            {mutation.error.message}
          </p>
        ) : null}
      </td>
    </tr>
  );

  function submit(target: Drawer) {
    if (target.kind === "activate")
      mutation.mutate({
        path: `/invitations/${target.invitation.id}/activate`,
        body: {
          expected_version: target.invitation.version,
          user_id: accountId,
          reason,
        },
      });
    else if (target.kind === "cancel")
      mutation.mutate({
        path: `/invitations/${target.invitation.id}/cancel`,
        body: {
          expected_version: target.invitation.version,
          active: false,
          reason,
        },
      });
    else if (target.kind === "member")
      mutation.mutate({
        path: `/memberships/${target.member.user_id}`,
        body: {
          expected_version: target.member.version,
          active: !target.member.active,
          reason,
        },
      });
  }

  return (
    <main className="workspace console-page licenses-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ADMINISTRAÇÃO DO TENANT</span>
          <h1>Licenças e convites</h1>
          <p>
            Convites pendentes reservam uma licença. O limite é verificado no
            convite e na ativação.
          </p>
        </div>
        <div className="toolbar">
          <Button
            variant="outline"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            <ArrowsClockwiseIcon aria-hidden /> Atualizar licenças
          </Button>
        </div>
      </header>
      {query.error ? (
        <NoticeBar tone="critical" role="alert" title="Licenças indisponíveis.">
          {query.error.message}
        </NoticeBar>
      ) : null}
      {query.isPending ? (
        <div className="console-stack" aria-busy="true">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}
      {mutation.isSuccess || invite.isSuccess ? (
        <NoticeBar tone="good">Alteração registrada e auditada.</NoticeBar>
      ) : null}
      {data ? (
        <div className="console-stack">
          <section
            className="panel license-summary"
            aria-label="Contrato de licenças"
          >
            <div className="license-figure">
              <span className="stat-label">Licenças contratadas</span>
              <strong className="stat-value">
                {data.used}
                <span> de {data.seats_limit}</span>
              </strong>
              <span className="stat-note">
                {data.used} de {data.seats_limit} licenças ocupadas ou
                reservadas.
              </span>
            </div>
            <div className="license-meter">
              <Meter
                value={data.used}
                max={data.seats_limit}
                label="Licenças ocupadas ou reservadas"
                legend={[
                  `${pendingCount} convite${pendingCount === 1 ? "" : "s"} pendente${pendingCount === 1 ? "" : "s"}`,
                  `${available} dispon${available === 1 ? "ível" : "íveis"}`,
                ]}
              />
              <p className="panel-note">
                Um convite reserva a licença até ser ativado ou cancelado. O
                limite também é aplicado pelo banco em toda ativação.
              </p>
            </div>
          </section>
          <div className="console-grid">
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Registrar convite</h2>
                  <p>
                    O registro não envia e-mail. A ativação exige uma conta com
                    e-mail verificado.
                  </p>
                </div>
              </div>
              <form
                className="panel-body form-grid"
                onSubmit={form.handleSubmit((body) => invite.mutate(body))}
              >
                <div className="field">
                  <label htmlFor="invite-email">E-mail</label>
                  <Input
                    id="invite-email"
                    type="email"
                    autoComplete="off"
                    {...form.register("email")}
                  />
                </div>
                <div className="field">
                  <label htmlFor="invite-role">Papel</label>
                  <select id="invite-role" {...form.register("role")}>
                    <option value="seller">Vendedor</option>
                    <option value="manager">Gestor</option>
                    <option value="auditor">Auditor</option>
                    <option value="admin">Administrador</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="invite-reason">
                    Justificativa do convite
                  </label>
                  <Input id="invite-reason" {...form.register("reason")} />
                  <span className="field-hint">
                    Fica registrada na auditoria do tenant junto com a autoria.
                  </span>
                </div>
                {Object.values(form.formState.errors).map((error, index) => (
                  <p className="inline-alert" role="alert" key={index}>
                    {error.message}
                  </p>
                ))}
                {invite.error ? (
                  <p className="inline-alert" role="alert">
                    {invite.error.message}
                  </p>
                ) : null}
                <div className="form-actions">
                  <Button disabled={invite.isPending || full}>
                    <UserPlusIcon aria-hidden /> Registrar convite
                  </Button>
                  {full ? (
                    <span className="form-status">
                      Contrato lotado: cancele um convite ou desative um membro.
                    </span>
                  ) : null}
                </div>
              </form>
            </section>
            <div className="console-stack">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Convites</h2>
                    <p>Ativar exige o ID de uma conta com e-mail verificado.</p>
                  </div>
                  <div className="panel-aside">
                    <StatusBadge tone={pendingCount ? "warning" : "neutral"}>
                      {pendingCount} pendente{pendingCount === 1 ? "" : "s"}
                    </StatusBadge>
                  </div>
                </div>
                {data.invitations.length ? (
                  <div
                    className="data-table"
                    role="region"
                    aria-label="Convites, tabela rolável"
                    tabIndex={0}
                  >
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">E-mail</th>
                          <th scope="col">Papel</th>
                          <th scope="col">Estado</th>
                          <th scope="col">
                            <span className="sr-only">Ações</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.invitations.map((item) => {
                          const [tone, label] =
                            invitationTone[
                              item.status as keyof typeof invitationTone
                            ] ?? (["neutral", item.status] as const);
                          const isOpen =
                            drawer?.kind !== "member" &&
                            drawer?.invitation.id === item.id;
                          return [
                            <tr key={item.id}>
                              <td>
                                <strong>{item.email}</strong>
                              </td>
                              <td>{roleLabels[item.role] ?? item.role}</td>
                              <td>
                                <StatusBadge tone={tone}>{label}</StatusBadge>
                              </td>
                              <td>
                                {item.status === "pending" ? (
                                  <div className="cell-actions">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      aria-label={`Ativar ${item.email}`}
                                      aria-expanded={
                                        isOpen && drawer?.kind === "activate"
                                      }
                                      onClick={() =>
                                        open({
                                          kind: "activate",
                                          invitation: item,
                                        })
                                      }
                                    >
                                      Ativar
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      aria-label={`Cancelar ${item.email}`}
                                      aria-expanded={
                                        isOpen && drawer?.kind === "cancel"
                                      }
                                      onClick={() =>
                                        open({
                                          kind: "cancel",
                                          invitation: item,
                                        })
                                      }
                                    >
                                      Cancelar
                                    </Button>
                                  </div>
                                ) : null}
                              </td>
                            </tr>,
                            isOpen && drawer?.kind === "activate"
                              ? drawerForm(
                                  `Ativar ${item.email}`,
                                  "Confirmar ativação",
                                  <div className="field" key="account">
                                    <label htmlFor="license-account">
                                      ID da conta verificada para ativação
                                    </label>
                                    <Input
                                      id="license-account"
                                      value={accountId}
                                      placeholder="UUID da conta no Auth"
                                      onChange={(event) =>
                                        setAccountId(event.target.value)
                                      }
                                    />
                                  </div>,
                                )
                              : null,
                            isOpen && drawer?.kind === "cancel"
                              ? drawerForm(
                                  `Cancelar ${item.email}`,
                                  "Confirmar cancelamento",
                                )
                              : null,
                          ];
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="data-empty">
                    Nenhum convite nesta página. Registre um convite para
                    reservar uma licença.
                  </p>
                )}
                <footer className="panel-footer">
                  <span>
                    {data.invitations.length} convite
                    {data.invitations.length === 1 ? "" : "s"} nesta página
                  </span>
                  <span className="pager">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!invitationCursor}
                      onClick={() => setInvitationCursor(null)}
                    >
                      Primeira página
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!data.next_invitation}
                      onClick={() => setInvitationCursor(data.next_invitation)}
                    >
                      Próximos convites
                    </Button>
                  </span>
                </footer>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Membros</h2>
                    <p>
                      Desativar preserva a autoria e o histórico; a licença é
                      liberada.
                    </p>
                  </div>
                </div>
                <div
                  className="data-table"
                  role="region"
                  aria-label="Membros, tabela rolável"
                  tabIndex={0}
                >
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Usuário</th>
                        <th scope="col">Papel</th>
                        <th scope="col">Estado</th>
                        <th scope="col">
                          <span className="sr-only">Ações</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.memberships.map((item) => {
                        const isOpen =
                          drawer?.kind === "member" &&
                          drawer.member.user_id === item.user_id;
                        const name = item.email ?? item.user_id;
                        return [
                          <tr key={item.user_id}>
                            <td>
                              <div className="cell-stack">
                                <strong>{name}</strong>
                                <small>{item.user_id}</small>
                              </div>
                            </td>
                            <td>{roleLabels[item.role] ?? item.role}</td>
                            <td>
                              <StatusBadge
                                tone={item.active ? "good" : "neutral"}
                              >
                                {item.active ? "Ativo" : "Inativo"}
                              </StatusBadge>
                            </td>
                            <td>
                              <div className="cell-actions">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  aria-label={`${item.active ? "Desativar" : "Reativar"} ${name}`}
                                  aria-expanded={isOpen}
                                  onClick={() =>
                                    open({ kind: "member", member: item })
                                  }
                                >
                                  {item.active ? "Desativar" : "Reativar"}
                                </Button>
                              </div>
                            </td>
                          </tr>,
                          isOpen
                            ? drawerForm(
                                `${item.active ? "Desativar" : "Reativar"} ${name}`,
                                item.active
                                  ? "Confirmar desativação"
                                  : "Confirmar reativação",
                              )
                            : null,
                        ];
                      })}
                    </tbody>
                  </table>
                </div>
                <footer className="panel-footer">
                  <span>
                    {data.memberships.length} membro
                    {data.memberships.length === 1 ? "" : "s"} nesta página
                  </span>
                  <span className="pager">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!memberCursor}
                      onClick={() => setMemberCursor(null)}
                    >
                      Primeira página
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!data.next_member}
                      onClick={() => setMemberCursor(data.next_member)}
                    >
                      Próximos membros
                    </Button>
                  </span>
                </footer>
              </section>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
