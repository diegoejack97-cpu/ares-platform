import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { createClient } from "@supabase/supabase-js";

const TENANT_ID = "20000000-0000-0000-0000-000000000001";
const EMAIL = "admin@ares.local";
const PASSWORD = "AresLocal!2026";
const WEBHOOK_SECRET = "local-dev-only-change-me";
const TICK_SECRET = "local-dev-tick-secret";

function localStatus() {
  const binary = join(
    process.cwd(),
    "node_modules",
    "supabase",
    "dist",
    "supabase.js",
  );
  const dockerDirectory = "C:\\Program Files\\Docker\\Docker\\resources\\bin";
  const output = execFileSync(
    process.execPath,
    [binary, "status", "-o", "json"],
    {
      cwd: process.cwd(),
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${dockerDirectory};${process.env.PATH ?? ""}`,
      },
    },
  );
  return JSON.parse(output.slice(output.indexOf("{")));
}

const status = localStatus();
const url = status.API_URL;
const databaseUrl = status.DB_URL;
const publishableKey = status.PUBLISHABLE_KEY ?? status.ANON_KEY;
const secretKey = status.SECRET_KEY ?? status.SERVICE_ROLE_KEY;

if (!/^http:\/\/(127\.0\.0\.1|localhost):/.test(url ?? "")) {
  throw new Error("Bootstrap recusado: a instância Supabase não é local.");
}
if (!databaseUrl || !publishableKey || !secretKey) {
  throw new Error(
    "Supabase local não retornou todas as credenciais necessárias.",
  );
}

const admin = createClient(url, secretKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});
const { data: usersPage, error: listError } = await admin.auth.admin.listUsers({
  perPage: 1000,
});
if (listError) throw listError;
let user = usersPage.users.find((candidate) => candidate.email === EMAIL);

if (user) {
  const { data, error } = await admin.auth.admin.updateUserById(user.id, {
    password: PASSWORD,
    email_confirm: true,
    app_metadata: { active_tenant_id: TENANT_ID },
  });
  if (error) throw error;
  user = data.user;
} else {
  const { data, error } = await admin.auth.admin.createUser({
    email: EMAIL,
    password: PASSWORD,
    email_confirm: true,
    app_metadata: { active_tenant_id: TENANT_ID },
  });
  if (error) throw error;
  user = data.user;
}

const { error: profileError } = await admin.from("profiles").upsert({
  user_id: user.id,
  display_name: "Administrador ARES",
  status: "active",
});
if (profileError) throw profileError;
// M6: membership activation fails closed without a seat contract. This synthetic
// local contract mirrors ai_budget_limits in seed.sql and is never overwritten.
const { data: quota, error: quotaReadError } = await admin
  .from("tenant_quotas")
  .select("tenant_id")
  .eq("tenant_id", TENANT_ID)
  .maybeSingle();
if (quotaReadError) throw quotaReadError;
if (!quota) {
  const { error: quotaError } = await admin.from("tenant_quotas").insert({
    tenant_id: TENANT_ID,
    seats_limit: 10,
    ai_daily_budget_brl: 0,
    ai_monthly_budget_brl: 0,
    usd_brl_rate: 5,
    rate_source: "SYNTHETIC local bootstrap rate; not a market quotation",
    updated_by: user.id,
  });
  if (quotaError) throw quotaError;
}
const { error: membershipError } = await admin
  .from("memberships")
  .upsert(
    { tenant_id: TENANT_ID, user_id: user.id, role: "admin", active: true },
    { onConflict: "tenant_id,user_id" },
  );
if (membershipError) throw membershipError;

const rootEnv = [
  "ARES_ENVIRONMENT=development",
  `ARES_FAKE_CRM_WEBHOOK_SECRET=${WEBHOOK_SECRET}`,
  'ARES_CORS_ORIGINS=["http://localhost:5173"]',
  "ARES_EVENT_JOURNAL_BACKEND=postgres",
  `ARES_DATABASE_URL=${databaseUrl}`,
  `ARES_TENANT_ID=${TENANT_ID}`,
  `ARES_SUPABASE_URL=${url}`,
  `ARES_SUPABASE_PUBLISHABLE_KEY=${publishableKey}`,
  `ARES_SUPABASE_SECRET_KEY=${secretKey}`,
  `ARES_TICK_SECRET=${TICK_SECRET}`,
  "",
].join("\n");
const webEnv = [
  "VITE_API_URL=http://localhost:8000",
  `VITE_SUPABASE_URL=${url}`,
  `VITE_SUPABASE_PUBLISHABLE_KEY=${publishableKey}`,
  "",
].join("\n");
const functionEnv = [`FAKE_CRM_WEBHOOK_SECRET=${WEBHOOK_SECRET}`, ""].join(
  "\n",
);

writeFileSync(join(process.cwd(), ".env"), rootEnv, { mode: 0o600 });
writeFileSync(join(process.cwd(), "apps", "web", ".env.local"), webEnv, {
  mode: 0o600,
});
writeFileSync(
  join(process.cwd(), "supabase", "functions", ".env"),
  functionEnv,
  {
    mode: 0o600,
  },
);

console.log("Bootstrap local concluído.");
console.log(`Login: ${EMAIL}`);
console.log(`Senha local: ${PASSWORD}`);
