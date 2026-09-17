import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowsClockwiseIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Meter, NoticeBar, StatusBadge, type Tone } from "@/components/console";
import type { LeadRecord, LeadResolve } from "@/features/agents/contract";
import { listLeads, createIntake, candidates, resolveLead } from "./api";
import "./leads.css";

const schema = z
  .object({
    name: z.string().trim().min(2, "Informe o nome do lead.").max(160),
    email: z.union([z.email("Informe um e-mail válido."), z.literal("")]),
    phone: z.string().trim().max(32),
  })
  .refine((v) => v.email || v.phone, {
    message: "Informe pelo menos um contato: e-mail ou telefone.",
    path: ["phone"],
  });

const leadStatus: Record<
  string,
  { tone: Tone | "accent"; label: string }
> = {
  pending: { tone: "warning", label: "Pendente" },
  creating: { tone: "info", label: "Criando no CRM" },
  created: { tone: "good", label: "Criado no CRM" },
  merged: { tone: "accent", label: "Mesclado" },
  discarded: { tone: "neutral", label: "Descartado" },
  uncertain: { tone: "critical", label: "Incerto" },
};

function LeadStatus({ status }: { status: string }) {
  const entry = leadStatus[status] ?? { tone: "neutral", label: status };
  return <StatusBadge tone={entry.tone}>{entry.label}</StatusBadge>;
}

const contacts = (lead: LeadRecord) =>
  [lead.email, lead.phone].filter(Boolean).join(" · ") || "Sem contato";

export function LeadsPage() {
  const [cursor, setCursor] = useState<string | null>(null),
    [selected, setSelected] = useState<string | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["leads", cursor],
    queryFn: () => listLeads(cursor),
    retry: false,
  });
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", email: "", phone: "" },
  });
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof schema>) =>
      createIntake({
        ...values,
        email: values.email || null,
        phone: values.phone || null,
        idempotency_key: key,
      }),
    onSuccess: (lead) => {
      form.reset();
      setKey(crypto.randomUUID());
      setCursor(null);
      setSelected(lead.id);
      void client.invalidateQueries({ queryKey: ["leads"] });
    },
  });
  const data = query.isError ? undefined : query.data;
  const selectedLead = data?.items.find((item) => item.id === selected);
  const errors = Object.values(form.formState.errors);
  return (
    <main className="workspace console-page leads-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">TRIAGEM HUMANA</span>
          <h1>Entrada de leads</h1>
          <p>
            Compare identidades antes de criar no CRM. O cadastro oficial
            permanece no CRM.
          </p>
        </div>
        <div className="toolbar">
          <Button
            variant="outline"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            <ArrowsClockwiseIcon aria-hidden /> Atualizar leads
          </Button>
        </div>
      </header>
      {query.error ? (
        <NoticeBar tone="critical" role="alert" title="Fila indisponível.">
          {query.error.message}
        </NoticeBar>
      ) : null}
      {query.isPending ? (
        <div className="console-stack" aria-busy="true">
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}
      {data ? (
        <div className="console-stack">
          <div className="console-grid">
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Enviar para triagem</h2>
                  <p>Nada é gravado no CRM até uma decisão humana.</p>
                </div>
              </div>
              <form
                className="panel-body form-grid"
                onSubmit={form.handleSubmit((values) =>
                  mutation.mutate(values),
                )}
              >
                <div className="field">
                  <label htmlFor="lead-name">Nome do lead</label>
                  <Input
                    id="lead-name"
                    autoComplete="off"
                    {...form.register("name")}
                  />
                </div>
                <div className="field">
                  <label htmlFor="lead-email">E-mail do lead</label>
                  <Input
                    id="lead-email"
                    type="email"
                    autoComplete="off"
                    {...form.register("email")}
                  />
                </div>
                <div className="field">
                  <label htmlFor="lead-phone">Telefone do lead</label>
                  <Input
                    id="lead-phone"
                    type="tel"
                    autoComplete="off"
                    {...form.register("phone")}
                  />
                  <span className="field-hint">
                    Informe e-mail ou telefone; a identidade é comparada com os
                    cadastros acessíveis a você.
                  </span>
                </div>
                {errors.length ? (
                  <p className="inline-alert" role="alert">
                    {errors[0]?.message ??
                      "Informe nome e pelo menos um contato válido."}
                  </p>
                ) : null}
                {mutation.error ? (
                  <p className="inline-alert" role="alert">
                    {mutation.error.message}
                  </p>
                ) : null}
                <div className="form-actions">
                  <Button disabled={mutation.isPending}>
                    Enviar para triagem
                  </Button>
                  {!data.can_create ? (
                    <span className="form-status">
                      O CRM conectado não oferece criação de lead.
                    </span>
                  ) : null}
                </div>
              </form>
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Fila de triagem</h2>
                  <p>Selecione uma entrada para comparar e decidir.</p>
                </div>
                <div className="panel-aside">
                  <StatusBadge tone="neutral">
                    {data.items.length} nesta página
                  </StatusBadge>
                </div>
              </div>
              {!data.items.length ? (
                <p className="data-empty">
                  Nenhum lead nesta página. Use o formulário para iniciar uma
                  triagem.
                </p>
              ) : (
                <ul className="record-list" aria-label="Leads em triagem">
                  {data.items.map((item) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        className="record-row"
                        aria-pressed={selected === item.id}
                        onClick={() => setSelected(item.id)}
                      >
                        <strong>{item.name}</strong>
                        <small>{contacts(item)}</small>
                        <span className="record-meta">
                          <LeadStatus status={item.status} />
                          <small>versão {item.version}</small>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <footer className="panel-footer">
                <span>Ordem de chegada · cursor por identificador</span>
                <span className="pager">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!cursor}
                    onClick={() => setCursor(null)}
                  >
                    Início
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!data.next_cursor}
                    onClick={() => setCursor(data.next_cursor)}
                  >
                    Próxima página
                  </Button>
                </span>
              </footer>
            </section>
          </div>
          {selectedLead ? (
            <LeadReview
              key={`${selectedLead.id}:${selectedLead.version}`}
              lead={selectedLead}
              canCreate={data.can_create}
            />
          ) : null}
        </div>
      ) : null}
    </main>
  );
}

function LeadReview({
  lead,
  canCreate,
}: {
  lead: LeadRecord;
  canCreate: boolean;
}) {
  const [reason, setReason] = useState(""),
    [target, setTarget] = useState("");
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["lead-candidates", lead.id],
    queryFn: () => candidates(lead.id),
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (action: LeadResolve["action"]) =>
      resolveLead(lead.id, {
        action,
        reason,
        target_subject_id: action === "merge" ? target : null,
        expected_version: lead.version,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["leads"] }),
  });
  const disabled =
    mutation.isPending ||
    reason.trim().length < 3 ||
    query.isError ||
    query.isPending;
  const pending = ["pending", "uncertain", "creating"].includes(lead.status);
  return (
    <section className="panel lead-review" aria-labelledby="lead-review-title">
      <div className="panel-heading">
        <div>
          <h2 id="lead-review-title">Revisar {lead.name}</h2>
          <p>
            Mesclar associa esta entrada a um cadastro existente, preserva o
            original e permite desfazer.
          </p>
        </div>
        <div className="panel-aside">
          <LeadStatus status={lead.status} />
          <StatusBadge tone="neutral">versão {lead.version}</StatusBadge>
        </div>
      </div>
      <div className="panel-body lead-review-body">
        <dl className="kv-list">
          <dt>Contato</dt>
          <dd>{contacts(lead)}</dd>
          <dt>Recebido em</dt>
          <dd>{new Date(lead.created_at).toLocaleString("pt-BR")}</dd>
          {lead.external_id ? (
            <>
              <dt>ID no CRM</dt>
              <dd>
                <code>{lead.external_id}</code>
              </dd>
            </>
          ) : null}
          <dt>Correlação</dt>
          <dd>
            <code>{lead.correlation_id}</code>
          </dd>
        </dl>
        <div className="lead-candidates">
          <h3>Possíveis duplicidades</h3>
          {query.isPending ? <Skeleton className="h-16 w-full" /> : null}
          {query.error ? (
            <p className="inline-alert" role="alert">
              {query.error.message}
            </p>
          ) : null}
          {query.data?.length === 0 ? (
            <p className="panel-note">
              Nenhum candidato encontrado entre os cadastros acessíveis. Criar
              no CRM é a única saída além de descartar.
            </p>
          ) : null}
          {query.data?.length ? (
            <ul className="option-list" aria-label="Candidatos a duplicidade">
              {query.data.map((item) => (
                <li key={item.id}>
                  <label className="option-card">
                    <input
                      type="radio"
                      name="candidate"
                      checked={target === item.id}
                      disabled={lead.status !== "pending"}
                      onChange={() => setTarget(item.id)}
                    />
                    <span className="option-copy">
                      <strong>{item.display_name}</strong>
                      <span className="option-reasons">
                        {item.reasons.map((reason) => (
                          <StatusBadge key={reason} tone="info">
                            {reason}
                          </StatusBadge>
                        ))}
                      </span>
                    </span>
                    <span className="option-score">
                      <strong>{Math.round(item.score * 100)}%</strong>
                      <Meter
                        value={item.score}
                        max={1}
                        label={`Similaridade com ${item.display_name}`}
                        severity={false}
                      />
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="lead-decision">
          <div className="field">
            <label htmlFor="lead-reason">Motivo da decisão</label>
            <Input
              id="lead-reason"
              value={reason}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
            />
            <span className="field-hint">
              Obrigatório. Fica na auditoria com a correlação desta entrada.
            </span>
          </div>
          {mutation.error ? (
            <p className="inline-alert" role="alert">
              {mutation.error.message}
            </p>
          ) : null}
          {!canCreate ? (
            <p className="inline-alert" role="status">
              O CRM conectado não oferece criação de lead. A ação está
              indisponível.
            </p>
          ) : null}
          <div className="form-actions">
            {pending ? (
              <>
                <Button
                  disabled={disabled || !canCreate}
                  onClick={() => mutation.mutate("create")}
                >
                  {lead.status === "uncertain"
                    ? "Reconciliar criação no CRM"
                    : "Confirmar criação no CRM"}
                </Button>
                <Button
                  variant="outline"
                  disabled={disabled || !target || lead.status !== "pending"}
                  onClick={() => mutation.mutate("merge")}
                >
                  Mesclar com selecionado
                </Button>
                <Button
                  variant="destructive"
                  disabled={disabled || lead.status !== "pending"}
                  onClick={() => mutation.mutate("discard")}
                >
                  Descartar entrada
                </Button>
              </>
            ) : null}
            {lead.status === "merged" ? (
              <Button
                variant="outline"
                disabled={disabled}
                onClick={() => mutation.mutate("undo")}
              >
                Desfazer mesclagem
              </Button>
            ) : null}
            {!pending && lead.status !== "merged" ? (
              <span className="form-status">
                Entrada encerrada. Nenhuma ação adicional disponível.
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
