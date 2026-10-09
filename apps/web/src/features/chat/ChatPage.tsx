import { ChatRecommendationAction } from "./chat-recommendation-action";
import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import {
  ArrowsClockwiseIcon,
  PaperPlaneTiltIcon,
  StopIcon,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/auth-context";
import type { ChatContext, ChatTool } from "@/features/agents/contract";
import {
  ChatError,
  getChat,
  sendChat,
  openFindingChat,
  saveChatFeedback,
} from "./api";
import {
  getSpecialistAnalysis,
  getOpportunityContext,
  startSpecialistAnalysis,
} from "@/features/opportunities/api";
import { ChatMarkdown } from "./ChatMarkdown";
import type { ChatExchange } from "@/features/agents/contract";
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
      key={`${session.user.id}:${session.user.app_metadata.active_tenant_id}:${params.get("scope")}:${params.get("finding")}`}
    />
  );
}

function ChatConversation() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  const client = useQueryClient();
  const location = useLocation();
  const returnTo =
    typeof location.state?.returnTo === "string" &&
    /^\/(radar|sentinels|pipeline|approvals|opportunities)(\/|$)/.test(
      location.state.returnTo,
    )
      ? location.state.returnTo
      : "/radar";
  const scope = params.get("scope") || undefined;
  const finding = params.get("finding") || undefined;
  const [older, setOlder] = useState<ChatExchange[]>([]);
  const [olderCursor, setOlderCursor] = useState<string | null | undefined>(
    undefined,
  );
  const [loadingOlder, setLoadingOlder] = useState(false);
  const opened = useRef(false);
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
      finding ?? "none",
    ],
    queryFn: async ({ signal }) => {
      if (finding && !opened.current) {
        await openFindingChat(finding, signal);
        opened.current = true;
        void client.invalidateQueries({ queryKey: ["sentinel-notifications"] });
      }
      return getChat(scope, signal, finding);
    },
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
      await sendChat(
        scope,
        question,
        abort.signal,
        (kind, value) => {
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
                      {
                        name: String(value.name),
                        status: String(value.status),
                      },
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
        },
        finding,
      );
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
      {data?.finding ? (
        <aside className="chat-origin" aria-label="Origem da conversa">
          <div>
            <span className="eyebrow">ALERTA DA SENTINELA</span>
            <strong>{data.finding.title}</strong>
            <span>
              {data.finding.rule_title} · Detectado em{" "}
              {new Date(data.finding.detected_at).toLocaleString("pt-BR")}
            </span>
            <p>
              {data.finding.condition_current
                ? "Condição presente na leitura atual."
                : "Alerta histórico: a condição original não está mais ativa."}{" "}
              {data.finding.changed ? "Os dados ou a regra mudaram." : ""}
            </p>
          </div>
          <ChatSpecialistAction opportunity={data.finding.opportunity_id} />
          <ChatRecommendationAction opportunity={data.finding.opportunity_id} />
          <nav aria-label="Navegação do alerta">
            <Link to={returnTo}>Voltar à tela anterior</Link>
            <Link to={`/opportunities/${data.finding.opportunity_id}`}>
              Ver oportunidade e análises
            </Link>
          </nav>
        </aside>
      ) : null}
      {scope && !finding ? (
        <ChatRecommendationAction opportunity={scope} />
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
            {(olderCursor === undefined ? data.next_before : olderCursor) ? (
              <li className="chat-older">
                <Button
                  variant="outline"
                  disabled={loadingOlder || busy}
                  onClick={async () => {
                    setLoadingOlder(true);
                    followLatest.current = false;
                    const element = transcript.current;
                    const height = element?.scrollHeight ?? 0;
                    try {
                      const previous = await getChat(
                        scope,
                        undefined,
                        finding,
                        (olderCursor === undefined
                          ? data.next_before
                          : olderCursor) ?? undefined,
                      );
                      setOlder((old) => [...previous.items, ...old]);
                      setOlderCursor(previous.next_before);
                      requestAnimationFrame(() => {
                        if (element)
                          element.scrollTop += element.scrollHeight - height;
                      });
                    } catch (failure) {
                      setError(
                        failure instanceof Error
                          ? failure
                          : new Error("Não foi possível carregar o histórico."),
                      );
                    } finally {
                      setLoadingOlder(false);
                    }
                  }}
                >
                  Carregar mensagens anteriores
                </Button>
              </li>
            ) : null}
            {data.items.length === 0 && !exchange ? (
              <li className="chat-welcome">
                <h2>Como posso ajudar?</h2>
                <p>
                  Pergunte sobre uma oportunidade ou descreva o que procura no
                  CRM.
                </p>
              </li>
            ) : null}
            {[...older, ...data.items]
              .filter(
                (item, index, all) =>
                  all.findIndex((other) => other.id === item.id) === index,
              )
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
                    {item.status === "succeeded" ? (
                      <ResponseFeedback message={item.id} />
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
          {data.finding && !busy ? (
            <div className="chat-suggestions" aria-label="Perguntas sugeridas">
              {data.finding.suggestions.map((suggestion) => (
                <button
                  type="button"
                  key={suggestion}
                  onClick={() => {
                    setText(suggestion);
                    composer.current?.focus();
                  }}
                >
                  {suggestion}
                </button>
              ))}
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

function ResponseFeedback({ message }: { message: string }) {
  const [rating, setRating] = useState<"helpful" | "unhelpful" | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  async function save(value: "helpful" | "unhelpful") {
    setBusy(true);
    setStatus("");
    try {
      await saveChatFeedback(message, value, reason);
      setRating(value);
      setStatus("Feedback registrado.");
    } catch {
      setStatus("Não foi possível registrar o feedback.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="chat-feedback" aria-label="Avaliar resposta">
      <button
        type="button"
        disabled={busy}
        aria-pressed={rating === "helpful"}
        onClick={() => void save("helpful")}
      >
        Útil
      </button>
      <button
        type="button"
        disabled={busy}
        aria-pressed={rating === "unhelpful"}
        onClick={() => setRating("unhelpful")}
      >
        Não útil
      </button>
      {rating === "unhelpful" ? (
        <>
          <input
            aria-label="Motivo do feedback"
            maxLength={500}
            value={reason}
            placeholder="O que faltou? (opcional)"
            onChange={(e) => setReason(e.target.value)}
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => void save("unhelpful")}
          >
            Enviar feedback
          </button>
        </>
      ) : null}
      <span role="status">{status}</span>
    </div>
  );
}

function ChatSpecialistAction({ opportunity }: { opportunity: string }) {
  const command = useRef<Parameters<typeof startSpecialistAnalysis>[0] | null>(
    null,
  );
  const state = useQuery({
    queryKey: ["specialist-analysis", opportunity],
    queryFn: () => getSpecialistAnalysis(opportunity),
    retry: false,
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.state ?? "")
        ? 3000
        : 30000,
  });
  const start = useMutation({
    mutationFn: async () => {
      if (!command.current) {
        const context = await getOpportunityContext(opportunity);
        command.current = {
          opportunity_id: opportunity,
          context_ref: context.context_ref,
          idempotency_key: crypto.randomUUID(),
        };
      }
      return startSpecialistAnalysis(command.current);
    },
    onSuccess: () => state.refetch(),
  });
  if (!state.data?.enabled) return null;
  const active = ["queued", "running"].includes(state.data.state);
  return (
    <div className="chat-specialist">
      <span role="status">
        {state.data.state === "ready"
          ? "Diagnóstico especialista vigente disponível."
          : active
            ? "Agentes de triagem e diagnóstico em andamento."
            : "Diagnóstico especializado requer uma análise atual."}
      </span>
      {state.data.can_request ? (
        <Button
          variant="outline"
          disabled={active || start.isPending}
          onClick={() => void start.mutate()}
        >
          Solicitar diagnóstico
        </Button>
      ) : null}
      <small>Usa a cota de IA do plano; não altera o CRM.</small>
      {start.isError ? (
        <p role="alert">
          Não foi possível solicitar o diagnóstico. Consulte o detalhe da
          oportunidade.
        </p>
      ) : null}
    </div>
  );
}
