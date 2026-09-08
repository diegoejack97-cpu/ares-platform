import { useState, type FormEvent } from "react";
import { ArrowRightIcon, LockKeyIcon } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { supabase } from "@/lib/supabase";
import { AresMark } from "@/components/ares-mark";

export function LoginPage() {
  const [email, setEmail] = useState("admin@ares.local");
  const [password, setPassword] = useState("AresLocal!2026");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (signInError)
      setError("Credenciais inválidas ou Auth local indisponível.");
    setSubmitting(false);
  }

  return (
    <main className="login-page">
      <section className="login-manifesto" aria-labelledby="login-title">
        <span className="login-kicker">ARES CONNECT · ACESSO OPERACIONAL</span>
        <h1 id="login-title">Receita recuperável começa com evidência.</h1>
        <p>
          Cada evento comercial entra com origem, identidade e correlação
          preservadas. Nenhum resultado é atribuído ao ARES sem trilha
          auditável.
        </p>
        <div className="login-chain" aria-label="Cadeia de valor do ARES">
          <span>OPORTUNIDADE</span>
          <i />
          <span>INTERVENÇÃO</span>
          <i />
          <span>RESULTADO</span>
          <i />
          <strong>VALOR</strong>
        </div>
      </section>
      <section className="login-card" aria-label="Entrar no ARES">
        <div className="login-brand">
          <span>
            <AresMark />
          </span>
          <div>
            <strong>ARES</strong>
            <small>PLATFORM</small>
          </div>
        </div>
        <LockKeyIcon size={24} aria-hidden />
        <h2>Entrar no ambiente</h2>
        <p>Tenant local · Serra Metais Distribuidora</p>
        <form onSubmit={submit}>
          <label htmlFor="email">E-mail</label>
          <Input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
          <label htmlFor="password">Senha</label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          {error ? (
            <div className="login-error" role="alert">
              {error}
            </div>
          ) : null}
          <Button type="submit" disabled={submitting}>
            {submitting ? "Validando…" : "Entrar"}
            <ArrowRightIcon aria-hidden />
          </Button>
        </form>
        <small className="login-footnote">
          Autenticação Supabase · isolamento RLS por tenant
        </small>
      </section>
    </main>
  );
}
