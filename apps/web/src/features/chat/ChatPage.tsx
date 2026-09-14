import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/auth-context";
import { getOpportunities } from "@/features/opportunities/api";
import { dateTime } from "@/features/opportunities/format";
import type { ChatContext } from "@/features/agents/contract";
import { ChatError, getChat, sendChat } from "./api";
import "./chat.css";

export function ChatPage() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  return (
    <ChatConversation
      key={`${session.user.id}:${session.user.app_metadata.active_tenant_id}:${params.get("scope")}`}
    />
  );
}

function ChatConversation() {
  const { session } = useAuth();
  const [params, setParams] = useSearchParams();
  const scope = params.get("scope") ?? "";
  const [text, setText] = useState(""),
    [answer, setAnswer] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  const [context, setContext] = useState<ChatContext | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<Error | null>(null);
  const controller = useRef<AbortController | null>(null);
  const identity = [
    session.user.id,
    session.user.app_metadata.active_tenant_id,
  ];
  const opportunities = useQuery({
    queryKey: ["chat-scopes", ...identity],
    queryFn: () => getOpportunities({}),
  });
  const query = useQuery({
    queryKey: ["chat", ...identity, scope],
    enabled: !!scope,
    queryFn: ({ signal }) => getChat(scope, signal),
    retry: false,
    refetchInterval: busy ? false : 30_000,
  });
  useEffect(() => {
    return () => {
      controller.current?.abort();
    };
  }, [scope, session.user.id, session.user.app_metadata.active_tenant_id]);
  const denied =
    query.error instanceof ChatError &&
    [401, 403, 404].includes(query.error.status);
  const data = denied ? undefined : query.data;
  const shownContext = denied ? null : (context ?? data?.context);
  async function send() {
    if (!text.trim() || busy) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError(null);
    setAnswer("");
    setTools([]);
    try {
      await sendChat(scope, text, abort.signal, (kind, value) => {
        if (kind === "token") setAnswer((old) => old + String(value.text));
        if (kind === "tool")
          setTools((old) => [
            ...old,
            `${value.name}: ${value.status === "running" ? "consultando" : "concluído"}`,
          ]);
        if (kind === "context") setContext(value as unknown as ChatContext);
      });
      await query.refetch();
      setText("");
      setAnswer("");
      setTools([]);
    } catch (failure) {
      setError(
        abort.signal.aborted
          ? new Error(
              "Resposta interrompida. O trecho recebido pode estar incompleto.",
            )
          : (failure as Error),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="workspace chat-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">ARES CONNECT / CONVERSA</span>
          <h1>Chat ARES</h1>
          <p>
            Consulte uma oportunidade com fatos, ferramentas e fontes visíveis.
          </p>
        </div>
      </header>
      <div className="chat-scope">
        <label htmlFor="chat-scope">Oportunidade</label>
        <select
          id="chat-scope"
          value={scope}
          disabled={busy}
          onChange={(event) => {
            setParams(event.target.value ? { scope: event.target.value } : {});
            setContext(null);
            setAnswer("");
            setTools([]);
            setError(null);
          }}
        >
          <option value="">Selecione uma oportunidade</option>
          {opportunities.data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title ?? item.id}
            </option>
          ))}
        </select>
        <Button
          variant="outline"
          disabled={!scope || busy}
          onClick={() => void query.refetch()}
        >
          Atualizar conversa
        </Button>
      </div>
      {opportunities.isError ? (
        <p role="alert">
          Não foi possível listar oportunidades.{" "}
          <Button
            variant="outline"
            onClick={() => void opportunities.refetch()}
          >
            Tentar novamente
          </Button>
        </p>
      ) : null}
      {!scope ? (
        <section className="empty-state">
          <h2>Escolha o contexto da conversa</h2>
          <p>Selecione uma oportunidade para consultar suas evidências.</p>
        </section>
      ) : null}
      {scope && query.isPending ? (
        <Skeleton
          className="h-64 w-full"
          role="status"
          aria-label="Carregando conversa"
        />
      ) : null}
      {query.error ? (
        <p role="alert">
          {query.error.message}{" "}
          {query.error instanceof ChatError ? query.error.correlationId : ""}
        </p>
      ) : null}
      {data ? (
        <div className="chat-layout">
          <section className="panel chat-conversation" aria-label="Conversa">
            {!data.model_available ? (
              <p className="chat-notice" role="status">
                Modelo não configurado. O administrador precisa configurar a
                chave OpenAI no servidor para habilitar respostas.
              </p>
            ) : null}
            <p className="chat-note">
              Cada pergunta consulta o contexto selecionado. O histórico abaixo
              é um registro; mensagens anteriores não entram na próxima
              resposta.
            </p>
            {data.items.length === 0 ? (
              <p className="empty-state">
                Ainda não há mensagens. Pergunte quais eventos explicam o risco
                desta oportunidade.
              </p>
            ) : null}
            <ol className="chat-history">
              {data.items.map((item) => (
                <li key={item.id}>
                  <p className="chat-question">
                    <strong>Você</strong>
                    {item.user_text}
                  </p>
                  <div className="chat-answer">
                    <strong>
                      ARES ·{" "}
                      {item.status === "succeeded"
                        ? "Concluído"
                        : item.status === "running"
                          ? "Em andamento"
                          : "Incompleto"}
                    </strong>
                    <p>{item.assistant_text || "Sem resposta concluída."}</p>
                    <details>
                      <summary>Ferramentas e fontes desta resposta</summary>
                      {item.tool_calls_json.map((tool, index) => (
                        <p key={index}>
                          {tool.name}: {tool.status}
                        </p>
                      ))}
                      {item.context_json.citations.map((citation) => (
                        <p key={citation.event_id}>
                          <Link
                            to={`/opportunities/${scope}#event-${citation.event_id}`}
                          >
                            {citation.event_type} · {citation.event_id}
                          </Link>
                        </p>
                      ))}
                      <p>
                        Hash: <code>{item.context_json.content_hash}</code>
                      </p>
                    </details>
                  </div>
                </li>
              ))}
            </ol>
            {tools.length ? (
              <ul
                className="chat-tools"
                aria-label="Ferramentas desta resposta"
              >
                {tools.map((tool, index) => (
                  <li key={index}>{tool}</li>
                ))}
              </ul>
            ) : null}
            {answer ? <p className="chat-stream">{answer}</p> : null}
            {busy ? <p role="status">Recebendo resposta…</p> : null}
            {error ? (
              <p role="alert">
                {error.message}{" "}
                {error instanceof ChatError ? error.correlationId : ""}
              </p>
            ) : null}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <label htmlFor="chat-text">Sua pergunta</label>
              <textarea
                id="chat-text"
                maxLength={1200}
                rows={3}
                value={text}
                onChange={(event) => setText(event.target.value)}
                disabled={busy || !data.model_available}
              />
              <div className="chat-actions">
                <span>{text.length}/1200</span>
                <Button
                  type="submit"
                  disabled={busy || !data.model_available || !text.trim()}
                >
                  Enviar pergunta
                </Button>
                {busy ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => controller.current?.abort()}
                  >
                    Interromper
                  </Button>
                ) : null}
              </div>
            </form>
          </section>
          <aside
            className="panel chat-context"
            aria-label="Contexto da resposta"
          >
            <h2>Contexto e fontes</h2>
            {shownContext ? (
              <>
                <p>Fonte: {shownContext.source}</p>
                <p>Snapshot: {dateTime(shownContext.captured_at)}</p>
                <p>
                  <strong>
                    {shownContext.tokens_upper_bound} /{" "}
                    {shownContext.token_limit}
                  </strong>{" "}
                  limite superior de tokens de evidência
                </p>
                <p>
                  Instruções:{" "}
                  {shownContext.instruction_tokens_upper_bound ??
                    "não informado"}{" "}
                  · Pergunta:{" "}
                  {shownContext.question_tokens_upper_bound ??
                    "aguardando envio"}
                </p>
                <p className="chat-note">
                  Contagem conservadora pelos bytes UTF-8. Instruções e pergunta
                  são adicionais. Não é contagem faturada pelo provedor.
                </p>
                <progress
                  value={shownContext.tokens_upper_bound}
                  max={shownContext.token_limit}
                  aria-label="Orçamento de contexto"
                />
                {shownContext.truncated ? (
                  <p>Parte dos eventos foi omitida para respeitar o limite.</p>
                ) : null}
                <p>
                  Hash: <code>{shownContext.content_hash}</code>
                </p>
                <ul>
                  {shownContext.citations.map((citation) => (
                    <li key={citation.event_id}>
                      <Link
                        to={`/opportunities/${scope}#event-${citation.event_id}`}
                      >
                        {citation.event_type} · {citation.event_id}
                      </Link>
                    </li>
                  ))}
                </ul>
                {!shownContext.citations.length ? (
                  <p>
                    Nenhum evento coube neste recorte. Não há evidência de
                    evento para citar.
                  </p>
                ) : null}
                <details>
                  <summary>Ver dados incluídos</summary>
                  <pre>{shownContext.content}</pre>
                </details>
              </>
            ) : null}
          </aside>
        </div>
      ) : null}
    </main>
  );
}
