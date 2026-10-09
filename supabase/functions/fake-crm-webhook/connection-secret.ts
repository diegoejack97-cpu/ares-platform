type Environment = (key: string) => string | undefined;
type Configuration = { connection_id: string; webhook_secret_env?: string };

export function selectWebhookSecret(connectionId: string, env: Environment) {
  const manifest = JSON.parse(env("ARES_CRM_CONNECTIONS") ?? "{}") as Record<
    string,
    Configuration
  >;
  const matches = Object.entries(manifest).filter(
    ([, config]) => config.connection_id === connectionId,
  );
  if (matches.length === 1) {
    const [tenantId, config] = matches[0];
    if (!/^ARES_CRM_SECRET_[A-Z0-9_]+$/.test(config.webhook_secret_env ?? ""))
      return null;
    const secret = env(config.webhook_secret_env!);
    if (!secret || secret.length < 24 || secret.startsWith("REPLACE_"))
      return null;
    return { secret, tenantId };
  }
  // The shared legacy key exists only for an explicitly local development environment.
  if (matches.length === 0 && env("ARES_ENVIRONMENT") === "development") {
    const secret = env("FAKE_CRM_WEBHOOK_SECRET");
    const tenantId = env("ARES_TENANT_ID");
    if (secret && tenantId) return { secret, tenantId };
  }
  return null;
}
