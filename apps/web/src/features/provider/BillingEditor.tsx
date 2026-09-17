import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { TenantConfiguration } from "@/features/agents/contract";
import { setBilling } from "./api";

const schema = z
  .object({
    state: z.enum(["active", "past_due", "degraded"]),
    due_since: z.string(),
    grace_until: z.string(),
    reason: z.string().trim().min(3).max(500),
  })
  .refine(
    (v) =>
      v.state === "active" ||
      (v.due_since && v.grace_until && v.grace_until >= v.due_since),
    { message: "Informe vencimento e prazo válidos." },
  );
export function BillingEditor({ data }: { data: TenantConfiguration }) {
  const client = useQueryClient();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      state: schema.shape.state.safeParse(data.billing?.state).data ?? "active",
      due_since: data.billing?.due_since ?? "",
      grace_until: data.billing?.grace_until ?? "",
      reason: "",
    },
  });
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof schema>) =>
      setBilling(data.tenant.id, {
        ...values,
        due_since: values.due_since || null,
        grace_until: values.grace_until || null,
        expected_version: data.tenant.version,
      }),
    onSuccess: () => {
      form.resetField("reason");
      void client.invalidateQueries({
        queryKey: ["provider-tenant", data.tenant.id],
      });
      void client.invalidateQueries({ queryKey: ["provider-tenants"] });
    },
  });
  return (
    <section className="provider-section">
      <h2>Cobrança</h2>
      <p>
        Estado registrado: {data.billing?.state ?? "Contrato não configurado"}.
        Prazo: {data.billing?.grace_until ?? "Não definido"}.
      </p>
      <p className="provider-note">
        Após o prazo, escrita e IA ficam indisponíveis. Leitura e histórico
        permanecem acessíveis.
      </p>
      <form onSubmit={form.handleSubmit((values) => mutation.mutate(values))}>
        <label htmlFor="billing-state">Novo estado de cobrança</label>
        <select id="billing-state" {...form.register("state")}>
          <option value="active">Adimplente</option>
          <option value="past_due">Em atraso, com prazo</option>
          <option value="degraded">Degradado após o prazo</option>
        </select>
        <label htmlFor="billing-due">Vencimento</label>
        <Input id="billing-due" type="date" {...form.register("due_since")} />
        <label htmlFor="billing-grace">Prazo de tolerância</label>
        <Input
          id="billing-grace"
          type="date"
          {...form.register("grace_until")}
        />
        <label htmlFor="billing-reason">Motivo da cobrança</label>
        <Input id="billing-reason" {...form.register("reason")} />
        {Object.keys(form.formState.errors).length ? (
          <p role="alert">Informe motivo e datas válidas para o contrato.</p>
        ) : null}
        {mutation.error ? <p role="alert">{mutation.error.message}</p> : null}
        {mutation.isSuccess ? (
          <p role="status">Cobrança atualizada e auditada.</p>
        ) : null}
        <Button disabled={mutation.isPending}>Salvar cobrança</Button>
      </form>
    </section>
  );
}
