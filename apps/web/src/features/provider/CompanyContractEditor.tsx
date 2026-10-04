import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PackageCode,
  TenantConfiguration,
} from "@/features/agents/contract";
import { setInitialAdmin, setPackage, setTenantStatus } from "./api";

export const packageLabels: Record<PackageCode, string> = {
  stellar: "STELLAR",
  ares_connect: "ARES Connect",
  ares_crm: "ARES CRM",
  full_connect: "Completo · Connect",
  full_crm: "Completo · CRM nativo",
};

const packages: Record<PackageCode, string[]> = {
  stellar: ["stellar"],
  ares_connect: ["ares_connect"],
  ares_crm: ["ares_crm"],
  full_connect: ["stellar", "ares_connect"],
  full_crm: ["stellar", "ares_crm"],
};

const reason = z.string().trim().min(3, "Informe o motivo.").max(500);
const packageSchema = z
  .object({
    package: z.enum([
      "stellar",
      "ares_connect",
      "ares_crm",
      "full_connect",
      "full_crm",
    ]),
    expires_at: z.string(),
    reason,
  })
  .refine(
    (value) =>
      !value.expires_at || new Date(value.expires_at).getTime() > Date.now(),
    { path: ["expires_at"], message: "Informe um vencimento futuro." },
  );
const statusSchema = z.object({
  status: z.enum(["active", "suspended"]),
  reason,
});
const initialAdminSchema = z.object({
  email: z.email("Informe um e-mail válido."),
  reason,
});

export function currentPackage(
  data: TenantConfiguration,
): PackageCode | undefined {
  const current = data.entitlements
    .filter((entry) => entry.status === "active")
    .map((entry) => entry.module)
    .sort()
    .join(",");
  return (Object.keys(packages) as PackageCode[]).find(
    (code) => packages[code].slice().sort().join(",") === current,
  );
}

function localDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function CompanyContractEditor({ data }: { data: TenantConfiguration }) {
  const client = useQueryClient();
  const company = data.tenant;
  const active = data.entitlements.filter((entry) => entry.status === "active");
  const priorFunnel = data.entitlements.find((entry) =>
    ["ares_connect", "ares_crm"].includes(entry.module),
  )?.module;
  const expiry = active.map((entry) => entry.expires_at).find(Boolean);
  const packageForm = useForm<z.infer<typeof packageSchema>>({
    resolver: zodResolver(packageSchema),
    defaultValues: {
      package: currentPackage(data),
      expires_at: localDateTime(expiry),
      reason: "",
    },
  });
  const statusForm = useForm<z.infer<typeof statusSchema>>({
    resolver: zodResolver(statusSchema),
    defaultValues: {
      status: company.status === "active" ? "active" : "suspended",
      reason: "",
    },
  });
  const initialAdminForm = useForm<z.infer<typeof initialAdminSchema>>({
    resolver: zodResolver(initialAdminSchema),
    defaultValues: { email: "", reason: "" },
  });
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: ["provider-tenant", company.id],
    });
    void client.invalidateQueries({ queryKey: ["provider-tenants"] });
  };
  const packageMutation = useMutation({
    mutationFn: (values: z.infer<typeof packageSchema>) =>
      setPackage(company.id, {
        package: values.package,
        expires_at: values.expires_at
          ? new Date(values.expires_at).toISOString()
          : null,
        reason: values.reason,
        expected_version: company.version,
      }),
    onSuccess: () => {
      packageForm.resetField("reason");
      refresh();
    },
  });
  const statusMutation = useMutation({
    mutationFn: (values: z.infer<typeof statusSchema>) =>
      setTenantStatus(company.id, {
        ...values,
        expected_version: company.version,
      }),
    onSuccess: () => {
      statusForm.resetField("reason");
      refresh();
    },
  });
  const initialAdminMutation = useMutation({
    mutationFn: (values: z.infer<typeof initialAdminSchema>) =>
      setInitialAdmin(company.id, {
        ...values,
        expected_version: company.version,
      }),
    onSuccess: () => {
      initialAdminForm.reset();
      refresh();
    },
  });
  const readyPlan = active.some(
    (entry) =>
      !entry.expires_at || new Date(entry.expires_at).getTime() > Date.now(),
  );
  const readyQuota = (data.quota?.seats_limit ?? 0) >= 1;
  const readyBilling = data.billing?.state === "active";
  const readyAdmin = data.initial_admin_assigned === true;

  return (
    <section
      className="provider-contract"
      aria-label="Contrato e liberação da empresa"
    >
      <div className="provider-contract-block">
        <h3>Plano da empresa</h3>
        <p className="provider-note">
          A atribuição ativa os módulos do pacote em uma operação auditada.
          Vencimento vazio significa contrato sem data final registrada.
        </p>
        <form
          onSubmit={packageForm.handleSubmit((values) =>
            packageMutation.mutate(values),
          )}
        >
          <label htmlFor="company-package">Pacote contratado</label>
          <select id="company-package" {...packageForm.register("package")}>
            <option value="">Selecione um pacote</option>
            {(Object.keys(packageLabels) as PackageCode[]).map((code) => (
              <option
                key={code}
                value={code}
                disabled={
                  (priorFunnel === "ares_connect" &&
                    packages[code].includes("ares_crm")) ||
                  (priorFunnel === "ares_crm" &&
                    packages[code].includes("ares_connect"))
                }
              >
                {packageLabels[code]}
              </option>
            ))}
          </select>
          {priorFunnel ? (
            <p className="provider-note">
              A troca entre Connect e CRM exige migração assistida.
            </p>
          ) : null}
          <label htmlFor="company-package-expiry">Válido até</label>
          <Input
            id="company-package-expiry"
            type="datetime-local"
            {...packageForm.register("expires_at")}
          />
          <p className="provider-note">
            Data e hora do seu dispositivo. Após esse horário, os módulos deixam
            de estar disponíveis.
          </p>
          <label htmlFor="company-package-reason">
            Motivo da atribuição ou renovação
          </label>
          <Input
            id="company-package-reason"
            {...packageForm.register("reason")}
          />
          {packageForm.formState.errors.package ||
          packageForm.formState.errors.reason ? (
            <p role="alert">
              Selecione o pacote e informe um motivo com pelo menos três
              caracteres.
            </p>
          ) : null}
          {packageForm.formState.errors.expires_at ? (
            <p role="alert">Informe um vencimento futuro.</p>
          ) : null}
          {packageMutation.error ? (
            <p role="alert">{packageMutation.error.message}</p>
          ) : null}
          {packageMutation.isSuccess ? (
            <p role="status">Plano atualizado e auditado.</p>
          ) : null}
          <Button disabled={packageMutation.isPending}>
            Atribuir ou renovar plano
          </Button>
        </form>
      </div>
      <div className="provider-contract-block">
        <h3>Liberação da empresa</h3>
        <p className="provider-note">
          Estado atual:{" "}
          <strong>
            {company.status === "active" ? "Liberada" : "Suspensa"}
          </strong>
          . A empresa administra seus usuários na própria área de licenças.
        </p>
        <ul
          className="provider-readiness"
          aria-label="Requisitos para liberação"
        >
          <li>{readyPlan ? "✓" : "○"} Plano ativo e dentro do prazo</li>
          <li>{readyQuota ? "✓" : "○"} Licenças e cotas configuradas</li>
          <li>{readyAdmin ? "✓" : "○"} Administrador inicial indicado</li>
          <li>
            {readyBilling ? "✓" : "○"} Cobrança configurada como adimplente
          </li>
        </ul>
        {!readyAdmin ? (
          <form
            className="provider-initial-admin"
            onSubmit={initialAdminForm.handleSubmit((values) =>
              initialAdminMutation.mutate(values),
            )}
          >
            <h4>Administrador inicial</h4>
            <p className="provider-note">
              Use uma conta já criada e com e-mail verificado. Depois, esse
              administrador gerencia os demais usuários em Licenças.
            </p>
            <label htmlFor="company-admin-email">E-mail do administrador</label>
            <Input
              id="company-admin-email"
              type="email"
              {...initialAdminForm.register("email")}
            />
            <label htmlFor="company-admin-reason">Motivo da indicação</label>
            <Input
              id="company-admin-reason"
              {...initialAdminForm.register("reason")}
            />
            {Object.keys(initialAdminForm.formState.errors).length ? (
              <p role="alert">Informe um e-mail válido e um motivo.</p>
            ) : null}
            {initialAdminMutation.error ? (
              <p role="alert">{initialAdminMutation.error.message}</p>
            ) : null}
            {initialAdminMutation.isSuccess ? (
              <p role="status">Administrador inicial indicado e auditado.</p>
            ) : null}
            <Button disabled={initialAdminMutation.isPending || !readyQuota}>
              Indicar administrador
            </Button>
          </form>
        ) : null}
        <form
          onSubmit={statusForm.handleSubmit((values) =>
            statusMutation.mutate(values),
          )}
        >
          <label htmlFor="company-status">Novo estado da empresa</label>
          <select id="company-status" {...statusForm.register("status")}>
            <option value="suspended">Suspensa</option>
            <option value="active">Liberada</option>
          </select>
          <label htmlFor="company-status-reason">
            Motivo da liberação ou suspensão
          </label>
          <Input
            id="company-status-reason"
            {...statusForm.register("reason")}
          />
          {statusForm.formState.errors.reason ? (
            <p role="alert">
              Informe um motivo com pelo menos três caracteres.
            </p>
          ) : null}
          {statusMutation.error ? (
            <p role="alert">{statusMutation.error.message}</p>
          ) : null}
          {statusMutation.isSuccess ? (
            <p role="status">Estado da empresa atualizado e auditado.</p>
          ) : null}
          <Button
            disabled={
              statusMutation.isPending ||
              (statusForm.watch("status") === "active" &&
                !(readyPlan && readyQuota && readyBilling && readyAdmin))
            }
          >
            Salvar liberação
          </Button>
        </form>
      </div>
    </section>
  );
}
