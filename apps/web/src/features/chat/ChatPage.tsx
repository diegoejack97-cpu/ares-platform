import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  ArrowsClockwiseIcon,
  PaperPlaneTiltIcon,
  StopIcon,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/auth-context";
import type { ChatContext, ChatTool } from "@/features/agents/contract";
import { ChatError, getChat, sendChat } from "./api";
import { ChatMarkdown } from "./ChatMarkdown";
import { ChatEvidence } from "./ChatEvidence";
import "./chat.css";

type LocalExchange = {
  id?: string;
  question: string;
  answer: string;
  context: ChatContext | null;
  tools: ChatTool[];
  status: "running" | "succeeded" | "failed";
};

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
  const [params] = useSearchParams();
  const scope = params.get("scope") || undefined;
  const [text, setText] = useState("");
  const [exchange, setExchange] = useState<LocalExchange | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("ARES está pensando…");
  const [error, setError] = useState<Error | null>(null);
  const controller = useRef<AbortController | null>(null);
  const queuedText = useRef("");
  const revealTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const revealFinished = useRef<(() => void) | null>(null);
  const transcript = useRef<HTMLOListElement | null>(null);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const followLatest = useRef(true);
  const query = useQuery({
    queryKey: [
      "chat",
      session.user.id,
      session.user.app_metadata.active_tenant_id,
      scope ?? "all",
    ],
    queryFn: ({ signal }) => getChat(scope, signal),
    retry: false,
    refetchInterval: busy ? false : 30_000,
    refetchOnWindowFocus: !busy,
  });
  useEffect(
    () => () => {
      controller.current?.abort();
      if (revealTimer.current) clearInterval(revealTimer.current);
    },
    [],
  );
  useLayoutEffect(() => {
    const history = transcript.current;
    if (!history || !followLatest.current) return;
    const replies = history.querySelectorAll<HTMLElement>(
      ".chat-message--assistant",
    );
    const latestReply = replies[replies.length - 1];
    if (
      !busy &&
      latestReply &&
      latestReply.offsetHeight > history.clientHeight - 24
    ) {
      const replyTop = latestReply.getBoundingClientRect().top;
      const historyTop = history.getBoundingClientRect().top;
      history.scrollTo({
        top: history.scrollTop + replyTop - historyTop - 8,
        behavior: "instant",
      });
    } else {
      history.scrollTo({ top: history.scrollHeight, behavior: "instant" });
    }
  }, [busy, exchange?.answer, exchange?.question, query.data?.items.length]);

  const denied =
    query.error instanceof ChatError &&
    [401, 403, 404].includes(query.error.status);
  const data = denied ? undefined : query.data;
  const localVisible =
    exchange && (busy || !data?.items.some((item) => item.id === exchange.id));

  function revealQueuedText() {
    if (revealTimer.current) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const next = queuedText.current;
      queuedText.current = "";
      setExchange((old) => (old ? { ...old, answer: old.answer + next } : old));
      revealFinished.current?.();
      revealFinished.current = null;
      return;
    }
    revealTimer.current = setInterval(() => {
      const next = queuedText.current.slice(0, 7);
      queuedText.current = queuedText.current.slice(next.length);
      if (next)
        setExchange((old) =>
          old ? { ...old, answer: old.answer + next } : old,
        );
      if (!queuedText.current) {
        if (revealTimer.current) clearInterval(revealTimer.current);
        revealTimer.current = null;
        revealFinished.current?.();
        revealFinished.current = null;
      }
    }, 55);
  }

  async function send() {
    if (!text.trim() || controller.current || !data) return;
    const question = text.trim();
    const abort = new AbortController();
    controller.current = abort;
    followLatest.current = true;
    setBusy(true);
    setError(null);
    setPhase("ARES está pensando…");
    queuedText.current = "";
    setExchange({
      question,
      answer: "",
      context: null,
      tools: [],
      status: "running",
    });
    setText("");
    try {
      await sendChat(scope, question, abort.signal, (kind, value) => {
        if (kind === "status" && typeof value.label === "string")
          setPhase(value.label);
        if (kind === "token") {
          setPhase("ARES está organizando a resposta…");
          queuedText.current += String(value.text ?? "");
          revealQueuedText();
        }
        if (kind === "tool") {
          if (value.status === "running")
            setPhase("ARES está consultando as fontes…");
          setExchange((old) =>
            old
              ? {
                  ...old,
                  tools: [
                    ...old.tools,
                    { name: String(value.name), status: String(value.status) },
                  ],
                }
              : old,
          );
        }
        if (kind === "context")
          setExchange((old) =>
            old
              ? {
                  ...old,
                  context: value as unknown as ChatContext,
                  id:
                    typeof value.message_id === "string"
                      ? value.message_id
                      : old.id,
                }
              : old,
          );
        if (kind === "done")
          setExchange((old) =>
            old
              ? {
                  ...old,
                  status: "succeeded",
                  id:
                    typeof value.message_id === "string"
                      ? value.message_id
                      : typeof value.id === "string"
                        ? value.id
                        : old.id,
                }
              : old,
          );
      });
      if (queuedText.current)
        await new Promise<void>((resolve, reject) => {
          revealFinished.current = resolve;
          abort.signal.addEventListener(
            "abort",
            () => reject(abort.signal.reason),
            {
              once: true,
            },
          );
        });
      if (abort.signal.aborted) throw abort.signal.reason;
      await query.refetch();
    } catch (failure) {
      if (revealTimer.current) clearInterval(revealTimer.current);
      revealTimer.current = null;
      if (!abort.signal.aborted && queuedText.current) {
        const remaining = queuedText.current;
        setExchange((old) =>
          old ? { ...old, answer: old.answer + remaining } : old,
        );
      }
      queuedText.current = "";
      revealFinished.current = null;
      setText(question);
      setExchange((old) => (old ? { ...old, status: "failed" } : old));
      setError(
        abort.signal.aborted
          ? new Error(
              "Resposta interrompida. O trecho recebido pode estar incompleto. Sua pergunta foi mantida para tentar novamente.",
            )
          : failure instanceof Error
            ? failure
            : new Error(
                "Não foi possível concluir a consulta. Tente novamente.",
              ),
      );
    } finally {
      controller.current = null;
      setBusy(false);
      composer.current?.focus();
    }
  }

  return (
    <main className="workspace chat-page">
      <header className="page-header chat-heading">
        <div>
          <span className="eyebrow">ARES CONNECT / CONVERSA</span>
          <h1>Chat ARES</h1>
          <p>
            Encontre oportunidades e consulte dados do ARES e do CRM pela
            conversa.
          </p>
        </div>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => void query.refetch()}
        >
          <ArrowsClockwiseIcon aria-hidden="true" />
          Atualizar conversa
        </Button>
      </header>
      {query.isPending ? (
        <Skeleton
          className="chat-loading"
          role="status"
          aria-label="Carregando conversa"
        />
      ) : null}
      {query.error ? (
        <div className="chat-error" role="alert">
          <p>{query.error.message}</p>
          {query.error instanceof ChatError && query.error.correlationId ? (
            <p>Correlação: {query.error.correlationId}</p>
          ) : null}
          {!denied && data ? (
            <p>
              O histórico exibido pode estar desatualizado. Use Atualizar
              conversa para tentar novamente.
            </p>
          ) : null}
          {!data && !denied ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => void query.refetch()}
            >
              Tentar novamente
            </Button>
          ) : null}
        </div>
      ) : null}
      {data ? (
        <section className="chat-conversation" aria-label="Conversa">
          {!data.model_available ? (
            <p className="chat-notice" role="status">
              Análises com IA indisponíveis no momento. Você ainda pode
              consultar as oportunidades disponíveis.
            </p>
          ) : null}
          <ol
            className="chat-history"
            ref={transcript}
            aria-label="Histórico da conversa"
            tabIndex={0}
            onScroll={() => {
              const element = transcript.current;
              if (element)
                followLatest.current =
                  element.scrollHeight -
                    element.scrollTop -
                    element.clientHeight <
                  80;
            }}
          >
            {data.items.length === 0 && !exchange ? (
              <li className="chat-welcome">
                <h2>Como posso ajudar?</h2>
                <p>
                  Pergunte sobre uma oportunidade ou descreva o que procura no
                  CRM.
                </p>
              </li>
            ) : null}
            {data.items
              .filter((item) => !(busy && item.id === exchange?.id))
              .map((item) => (
                <Fragment key={item.id}>
                  <li
                    className="chat-message chat-message--user"
                    aria-label="Sua mensagem"
                  >
                    <p>{item.user_text}</p>
                  </li>
                  <li
                    className="chat-message chat-message--assistant"
                    aria-label="Resposta do ARES"
                  >
                    {item.assistant_text ? (
                      <ChatMarkdown>{item.assistant_text}</ChatMarkdown>
                    ) : (
                      <p className="chat-note">
                        {item.status === "running"
                          ? "Resposta em andamento. Atualize a conversa para ver o resultado."
                          : "Sem resposta concluída."}
                      </p>
                    )}
                    {item.status !== "succeeded" && item.assistant_text ? (
                      <p className="chat-notice">
                        Esta resposta está incompleta.
                      </p>
                    ) : null}
                    <ChatEvidence
                      context={item.context_json}
                      tools={item.tool_calls_json}
                      scope={scope}
                    />
                  </li>
                </Fragment>
              ))}
            {localVisible ? (
              <Fragment>
                <li
                  className="chat-message chat-message--user chat-message--outgoing"
                  aria-label="Sua mensagem"
                >
                  <p>{exchange.question}</p>
                </li>
                <li
                  className="chat-message chat-message--assistant"
                  aria-label="Resposta do ARES"
                >
                  {exchange.answer ? (
                    <ChatMarkdown>{exchange.answer}</ChatMarkdown>
                  ) : null}
                  {busy && !exchange.answer ? (
                    <div
                      className="chat-pending"
                      role="status"
                      aria-label={phase}
                    >
                      <span className="chat-typing-dots" aria-hidden="true">
                        <span className="chat-typing-dot" />
                        <span className="chat-typing-dot" />
                        <span className="chat-typing-dot" />
                      </span>
                    </div>
                  ) : null}
                  {!busy ? (
                    <ChatEvidence
                      context={exchange.context}
                      tools={exchange.tools}
                      scope={scope}
                    />
                  ) : null}
                </li>
              </Fragment>
            ) : null}
          </ol>
          {error ? (
            <div className="chat-error" role="alert">
              <p>{error.message}</p>
              {error instanceof ChatError && error.correlationId ? (
                <p>Correlação: {error.correlationId}</p>
              ) : null}
            </div>
          ) : null}
          <form
            className="chat-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <label htmlFor="chat-text">Sua pergunta</label>
            <div className="chat-composer-box">
              <textarea
                id="chat-text"
                ref={composer}
                maxLength={1200}
                rows={1}
                value={text}
                placeholder="Pergunte ao ARES…"
                aria-describedby="chat-input-hint chat-text-count"
                onChange={(event) => setText(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void send();
                  }
                }}
                disabled={busy}
              />
              <div className="chat-actions">
                <span
                  className="chat-note chat-keyboard-hint"
                  id="chat-input-hint"
                >
                  Enter envia · Shift+Enter quebra a linha
                </span>
                <span
                  className="chat-note chat-text-count"
                  id="chat-text-count"
                >
                  {text.length}/1200
                </span>
                {busy ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => controller.current?.abort()}
                  >
                    <StopIcon aria-hidden="true" />
                    Interromper
                  </Button>
                ) : null}
                <Button
                  type="submit"
                  disabled={busy || !text.trim()}
                  aria-label="Enviar mensagem"
                >
                  <PaperPlaneTiltIcon aria-hidden="true" />
                  Enviar
                </Button>
              </div>
            </div>
          </form>
        </section>
      ) : null}
    </main>
  );
}
