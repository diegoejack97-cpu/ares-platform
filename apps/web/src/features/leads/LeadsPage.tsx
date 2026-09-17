import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { LeadRecord, LeadResolve } from "@/features/agents/contract";
import { listLeads, createIntake, candidates, resolveLead } from "./api";
import "../impact/impact.css";
import "../provider/provider.css";
const schema = z
  .object({
    name: z.string().trim().min(2).max(160),
    email: z.union([z.email(), z.literal("")]),
    phone: z.string().max(32),
  })
  .refine((v) => v.email || v.phone);
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
    onSuccess: () => {
      form.reset();
      setKey(crypto.randomUUID());
      setCursor(null);
      void client.invalidateQueries({ queryKey: ["leads"] });
    },
  });
  const data = query.isError ? undefined : query.data;
  const selectedLead = data?.items.find((item) => item.id === selected);
  return (
    <main className="workspace impact-page">
      <header className="page-heading">
        <span className="eyebrow">TRIAGEM HUMANA</span>
        <h1>Entrada de leads</h1>
        <p>
          Compare identidades antes de criar no CRM. O cadastro oficial
          permanece no CRM.
        </p>
      </header>
      <Button variant="outline" onClick={() => void query.refetch()}>
        Atualizar leads
      </Button>
      {query.error ? <p role="alert">{query.error.message}</p> : null}
      {query.isPending ? <Skeleton className="h-64 w-full" /> : null}
      {data ? (
        <>
          <div className="provider-layout">
            <section className="panel provider-section">
              <h2>Enviar para triagem</h2>
              <form
                onSubmit={form.handleSubmit((values) =>
                  mutation.mutate(values),
                )}
              >
                <label htmlFor="lead-name">Nome do lead</label>
                <Input id="lead-name" {...form.register("name")} />
                <label htmlFor="lead-email">E-mail do lead</label>
                <Input
                  id="lead-email"
                  type="email"
                  {...form.register("email")}
                />
                <label htmlFor="lead-phone">Telefone do lead</label>
                <Input id="lead-phone" type="tel" {...form.register("phone")} />
                {Object.keys(form.formState.errors).length ? (
                  <p role="alert">
                    Informe nome e pelo menos um contato válido.
                  </p>
                ) : null}
                {mutation.error ? (
                  <p role="alert">{mutation.error.message}</p>
                ) : null}
                <Button disabled={mutation.isPending}>
                  Enviar para triagem
                </Button>
              </form>
            </section>
            <section className="panel provider-section">
              <h2>Fila de triagem</h2>
              {!data.items.length ? (
                <p>
                  Nenhum lead nesta página. Use o formulário para iniciar uma
                  triagem.
                </p>
              ) : (
                <ul className="impact-interventions">
                  {data.items.map((item) => (
                    <li key={item.id}>
                      <Button
                        variant="outline"
                        onClick={() => setSelected(item.id)}
                      >
                        {item.name}
                      </Button>
                      <span>
                        {item.status} · versão {item.version}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="impact-actions">
                <Button
                  variant="outline"
                  disabled={!cursor}
                  onClick={() => setCursor(null)}
                >
                  Início
                </Button>
                <Button
                  variant="outline"
                  disabled={!data.next_cursor}
                  onClick={() => setCursor(data.next_cursor)}
                >
                  Próxima página
                </Button>
              </div>
            </section>
          </div>
          {selectedLead ? (
            <LeadReview
              key={`${selectedLead.id}:${selectedLead.version}`}
              lead={selectedLead}
              canCreate={data.can_create}
            />
          ) : null}
        </>
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
    <section className="panel provider-section">
      <h2>Revisar {lead.name}</h2>
      <p>
        Estado: {lead.status}. Mesclar associa esta entrada a um cadastro
        existente, preserva o original e permite desfazer.
      </p>
      {query.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {query.error ? <p role="alert">{query.error.message}</p> : null}
      <ul className="impact-interventions">
        {query.data?.map((item) => (
          <li key={item.id}>
            <label>
              <input
                type="radio"
                name="candidate"
                checked={target === item.id}
                onChange={() => setTarget(item.id)}
              />{" "}
              {item.display_name} · Similaridade {Math.round(item.score * 100)}%
            </label>
            <span>{item.reasons.join(" · ")}</span>
          </li>
        ))}
      </ul>
      {query.data?.length === 0 ? (
        <p>Nenhum candidato encontrado entre os cadastros acessíveis.</p>
      ) : null}
      <label htmlFor="lead-reason">Motivo da decisão</label>
      <Input
        id="lead-reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      {mutation.error ? <p role="alert">{mutation.error.message}</p> : null}
      {!canCreate ? (
        <p>
          O CRM conectado não oferece criação de lead. A ação está indisponível.
        </p>
      ) : null}
      <div className="impact-actions">
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
              variant="outline"
              disabled={disabled || lead.status !== "pending"}
              onClick={() => mutation.mutate("discard")}
            >
              Descartar entrada
            </Button>
          </>
        ) : null}
        {lead.status === "merged" ? (
          <Button disabled={disabled} onClick={() => mutation.mutate("undo")}>
            Desfazer mesclagem
          </Button>
        ) : null}
      </div>
      <code>Correlação: {lead.correlation_id}</code>
    </section>
  );
}
