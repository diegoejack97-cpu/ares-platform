import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { AresMark } from "@/components/ares-mark";
import {
  createTenant,
  listTenants,
  providerAuth,
  ProviderError,
  setEntitlement,
  tenantConfiguration,
} from "./api";
import "./provider.css";
import { BillingEditor } from "./BillingEditor";
import { QuotaEditor } from "./QuotaEditor";

const reason = z
  .string()
  .trim()
  .min(3, "Informe o motivo (mínimo 3 caracteres).")
  .max(500);
const createSchema = z.object({
  name: z.string().trim().min(2).max(160),
  slug: z
    .string()
    .min(2)
    .max(80)
    .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
  reason,
});
const entitlementSchema = z.object({
  module: z.enum(["stellar", "ares_connect", "ares_crm"]),
  status: z.enum(["active", "suspended", "revoked"]),
  reason,
});

function ErrorNotice({ error }: { error: Error | null }) {
  return error ? (
    <div role="alert">
      <p>{error.message}</p>
      {error instanceof ProviderError && error.correlationId ? (
        <code>Correlação: {error.correlationId}</code>
      ) : null}
    </div>
  ) : null;
}

export function ProviderPage() {
  const [session, setSession] = useState<Session | null>(null),
    [loading, setLoading] = useState(true);
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
        },
      }),
  );
  useEffect(() => {
    let active = true;
    void providerAuth.auth.getSession().then(({ data }) => {
      if (active) {
        setSession(data.session);
        setLoading(false);
      }
    });
    const { data } = providerAuth.auth.onAuthStateChange((event, next) => {
      if (event !== "TOKEN_REFRESHED") client.clear();
      setSession(next);
      setLoading(false);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
      client.clear();
    };
  }, [client]);
  if (loading)
    return (
      <main className="workspace">
        <Skeleton
          className="h-64 w-full"
          aria-label="Carregando acesso do provedor"
        />
      </main>
    );
  return (
    <QueryClientProvider client={client}>
      {session ? <ProviderPanel key={session.user.id} /> : <ProviderLogin />}
    </QueryClientProvider>
  );
}

function ProviderLogin() {
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<Error | null>(null);
  return (
    <main className="login-page provider-login">
      <section className="login-manifesto">
        <span className="login-kicker">NOGUEIRA!IA / PROVEDOR</span>
        <h1>Contratos e acesso sob controle.</h1>
        <p>
          Administre tenants e módulos com autoria, motivo e histórico
          preservados.
        </p>
        <a href="/radar">Voltar ao produto</a>
      </section>
      <section className="login-card">
        <div className="login-brand">
          <AresMark />
        </div>
        <h2>Acesso do provedor</h2>
        <p>Use sua conta dedicada. A sessão do produto permanece separada.</p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError(null);
            try {
              const { error: failure } =
                await providerAuth.auth.signInWithPassword({ email, password });
              if (failure)
                throw new Error(
                  "Credenciais inválidas ou autenticação indisponível.",
                );
            } catch (failure) {
              setError(failure as Error);
            } finally {
              setBusy(false);
              setPassword("");
            }
          }}
        >
          <label htmlFor="provider-email">E-mail do provedor</label>
          <Input
            id="provider-email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
          <label htmlFor="provider-password">Senha do provedor</label>
          <Input
            id="provider-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          <ErrorNotice error={error} />
          <Button disabled={busy}>
            {busy ? "Entrando…" : "Entrar como provedor"}
          </Button>
        </form>
      </section>
    </main>
  );
}

function ProviderPanel() {
  const [cursor, setCursor] = useState<string | null>(null),
    [selected, setSelected] = useState("");
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["provider-tenants", cursor],
    queryFn: ({ signal }) => listTenants(cursor, signal),
  });
  const denied =
    query.error instanceof ProviderError &&
    [401, 403].includes(query.error.status);
  const tenants = denied ? undefined : query.data;
  const form = useForm<z.infer<typeof createSchema>>({
    resolver: zodResolver(createSchema),
    defaultValues: { name: "", slug: "", reason: "" },
  });
  const mutation = useMutation({
    mutationFn: createTenant,
    onSuccess: (tenant) => {
      form.reset();
      setSelected(tenant.id);
      void client.invalidateQueries({ queryKey: ["provider-tenants"] });
    },
  });
  return (
    <main className="workspace provider-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">NOGUEIRA!IA / ADMINISTRAÇÃO</span>
          <h1>Painel do provedor</h1>
          <p>
            Tenants e módulos contratados. Cada alteração registra autoria e
            motivo.
          </p>
        </div>
        <div className="provider-actions">
          <a href="/radar">Abrir produto</a>
          <Button
            variant="outline"
            onClick={() => void providerAuth.auth.signOut({ scope: "local" })}
          >
            Sair do provedor
          </Button>
        </div>
      </header>
      <ErrorNotice error={query.error} />
      {query.isError ? (
        <Button variant="outline" onClick={() => void query.refetch()}>
          Tentar novamente
        </Button>
      ) : null}
      {query.isPending ? (
        <Skeleton className="h-64 w-full" aria-label="Carregando tenants" />
      ) : null}
      {tenants ? (
        <>
          <div className="provider-layout">
            <section className="panel provider-section">
              <h2>Tenants</h2>
              <p className="provider-note">
                Fonte: cadastro administrativo. Esta consulta é auditada.
              </p>
              {!tenants.items.length ? (
                <p>
                  Nenhum tenant nesta página. Cadastre um novo tenant ou volte
                  ao início.
                </p>
              ) : (
                <ul className="provider-tenants">
                  {tenants.items.map((tenant) => (
                    <li key={tenant.id}>
                      <Button
                        variant="outline"
                        aria-pressed={selected === tenant.id}
                        onClick={() => setSelected(tenant.id)}
                      >
                        {tenant.name}
                      </Button>
                      <span>
                        {tenant.slug} · {tenant.status} · v{tenant.version}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="provider-actions">
                <Button
                  variant="outline"
                  disabled={!cursor}
                  onClick={() => setCursor(null)}
                >
                  Início
                </Button>
                <Button
                  variant="outline"
                  disabled={!tenants.next_cursor}
                  onClick={() => setCursor(tenants.next_cursor ?? null)}
                >
                  Próxima página
                </Button>
                <Button variant="outline" onClick={() => void query.refetch()}>
                  Atualizar tenants
                </Button>
              </div>
            </section>
            <section className="panel provider-section">
              <h2>Criar tenant</h2>
              <p className="provider-note">
                Módulos e usuários serão habilitados separadamente.
              </p>
              <form
                onSubmit={form.handleSubmit((values) =>
                  mutation.mutate(values),
                )}
              >
                <label htmlFor="tenant-name">Nome</label>
                <Input id="tenant-name" {...form.register("name")} />
                <label htmlFor="tenant-slug">Identificador</label>
                <Input id="tenant-slug" {...form.register("slug")} />
                <small>Minúsculas, números e hífens.</small>
                <label htmlFor="create-reason">Motivo da criação</label>
                <Input id="create-reason" {...form.register("reason")} />
                {Object.keys(form.formState.errors).length ? (
                  <p role="alert">
                    Preencha nome, identificador válido e motivo com pelo menos
                    três caracteres.
                  </p>
                ) : null}
                <ErrorNotice error={mutation.error} />
                {mutation.isSuccess ? (
                  <p role="status">Tenant criado e registrado na auditoria.</p>
                ) : null}
                <Button disabled={mutation.isPending}>Criar tenant</Button>
              </form>
            </section>
          </div>
          {selected ? (
            <EntitlementEditor key={selected} tenantId={selected} />
          ) : (
            <p className="provider-note">
              Selecione um tenant para revisar os módulos.
            </p>
          )}
        </>
      ) : null}
    </main>
  );
}

function EntitlementEditor({ tenantId }: { tenantId: string }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["provider-tenant", tenantId],
    queryFn: ({ signal }) => tenantConfiguration(tenantId, signal),
  });
  const form = useForm<z.infer<typeof entitlementSchema>>({
    resolver: zodResolver(entitlementSchema),
    defaultValues: { status: "active", reason: "" },
  });
  const mutation = useMutation({
    mutationFn: (values: z.infer<typeof entitlementSchema>) => {
      if (!query.data) throw new Error("Recarregue a configuração.");
      return setEntitlement(tenantId, {
        ...values,
        expected_version: query.data.tenant.version,
        expires_at:
          query.data.entitlements.find((item) => item.module === values.module)
            ?.expires_at ?? null,
      });
    },
    onSuccess: () => {
      form.resetField("reason");
      void query.refetch();
      void client.invalidateQueries({ queryKey: ["provider-tenants"] });
    },
  });
  const data = query.isError ? undefined : query.data;
  return (
    <section className="panel provider-section">
      <h2>Módulos do tenant</h2>
      <ErrorNotice error={query.error} />
      <Button
        variant="outline"
        disabled={query.isFetching || mutation.isPending}
        onClick={() => void query.refetch()}
      >
        Recarregar configuração
      </Button>
      {query.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {data ? (
        <>
          <p>
            {data.tenant.name} · versão {data.tenant.version}
          </p>
          <ul>
            {data.entitlements.map((item) => (
              <li key={item.module}>
                {item.module}: {item.status}
                {item.expires_at
                  ? ` · expira em ${new Date(item.expires_at).toLocaleString("pt-BR")}`
                  : ""}
              </li>
            ))}
          </ul>
          <form
            onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          >
            <label htmlFor="provider-module">Módulo</label>
            <select id="provider-module" {...form.register("module")}>
              <option value="">Selecione um módulo</option>
              <option value="stellar">STELLAR</option>
              <option
                value="ares_connect"
                disabled={data.entitlements.some(
                  (item) => item.module === "ares_crm",
                )}
              >
                ARES Connect
              </option>
              <option
                value="ares_crm"
                disabled={data.entitlements.some(
                  (item) => item.module === "ares_connect",
                )}
              >
                ARES CRM
              </option>
            </select>
            {form.formState.errors.module ? (
              <p role="alert">Selecione um módulo disponível.</p>
            ) : null}
            <p className="provider-note">
              Troca do dono do funil exige migração assistida.
            </p>
            <label htmlFor="provider-status">Estado do módulo</label>
            <select id="provider-status" {...form.register("status")}>
              <option value="active">Ativo</option>
              <option value="suspended">Suspenso</option>
              <option value="revoked">Revogado</option>
            </select>
            <label htmlFor="entitlement-reason">Motivo da alteração</label>
            <Input id="entitlement-reason" {...form.register("reason")} />
            {form.formState.errors.reason ? (
              <p role="alert">{form.formState.errors.reason.message}</p>
            ) : null}
            <ErrorNotice error={mutation.error} />
            {mutation.isSuccess ? (
              <p role="status">Módulo atualizado e auditado.</p>
            ) : null}
            <Button disabled={mutation.isPending || query.isFetching}>
              Salvar módulo
            </Button>
          </form>
          <BillingEditor key={data.tenant.version} data={data} />
          <QuotaEditor key={`quota-${data.tenant.version}`} data={data} />
        </>
      ) : null}
    </section>
  );
}
