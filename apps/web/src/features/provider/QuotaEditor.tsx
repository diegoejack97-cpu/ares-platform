import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { TenantConfiguration } from "@/features/agents/contract";
import { setQuota } from "./api";
const schema = z
  .object({
    seats_limit: z.number().int().min(0),
    ai_daily_budget_brl: z.number().min(0),
    ai_monthly_budget_brl: z.number().min(0),
    usd_brl_rate: z.number().positive(),
    rate_source: z.string().trim().min(3),
    reason: z.string().trim().min(3),
  })
  .refine((v) => v.ai_monthly_budget_brl >= v.ai_daily_budget_brl);
export function QuotaEditor({ data }: { data: TenantConfiguration }) {
  const client = useQueryClient();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: data.quota
      ? {
          seats_limit: data.quota.seats_limit,
          ai_daily_budget_brl: Number(data.quota.ai_daily_budget_brl),
          ai_monthly_budget_brl: Number(data.quota.ai_monthly_budget_brl),
          usd_brl_rate: Number(data.quota.usd_brl_rate),
          rate_source: data.quota.rate_source,
          reason: "",
        }
      : undefined,
  });
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof schema>) =>
      setQuota(data.tenant.id, {
        ...values,
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
      <h2>Cotas e licenças</h2>
      <p>
        Orçamentos em BRL. A taxa fica preservada em cada consumo. Reservas com
        custo desconhecido continuam comprometendo saldo.
      </p>
      <form onSubmit={form.handleSubmit((v) => mutation.mutate(v))}>
        {(
          [
            ["seats_limit", "Licenças contratadas"],
            ["ai_daily_budget_brl", "Orçamento diário (BRL)"],
            ["ai_monthly_budget_brl", "Orçamento mensal (BRL)"],
            ["usd_brl_rate", "Reais por dólar (USD/BRL)"],
          ] as const
        ).map(([key, label]) => (
          <div key={key}>
            <label htmlFor={key}>{label}</label>
            <Input
              id={key}
              type="number"
              min="0"
              step={key === "seats_limit" ? "1" : "0.000001"}
              {...form.register(key, { valueAsNumber: true })}
            />
          </div>
        ))}
        <label htmlFor="rate-source">Fonte e data da taxa</label>
        <Input id="rate-source" {...form.register("rate_source")} />
        <label htmlFor="quota-reason">Motivo da alteração de cotas</label>
        <Input id="quota-reason" {...form.register("reason")} />
        {Object.keys(form.formState.errors).length ? (
          <p role="alert">
            Preencha os limites, a taxa positiva e o motivo. O mensal não pode
            ser menor que o diário.
          </p>
        ) : null}
        {mutation.error ? <p role="alert">{mutation.error.message}</p> : null}
        {mutation.isSuccess ? (
          <p role="status">Cotas e licenças atualizadas e auditadas.</p>
        ) : null}
        <Button disabled={mutation.isPending}>Salvar cotas e licenças</Button>
      </form>
      <p className="provider-note">
        Na primeira configuração, o consumo USD anterior é convertido como saldo
        inicial pela taxa informada e fica auditado. Não é uma cotação
        histórica.
      </p>
    </section>
  );
}
