import { Link } from "react-router-dom";
import { dateTime } from "@/features/opportunities/format";
import type {
  ChatCitation,
  ChatContext,
  ChatTool,
} from "@/features/agents/contract";

const toolLabels: Record<string, string> = {
  get_context: "Consultar evidências",
  search_opportunities: "Buscar oportunidades",
  search_crm: "Consultar CRM",
};

function Citation({
  citation,
  scope,
}: {
  citation: ChatCitation;
  scope?: string;
}) {
  const opportunity =
    (citation as ChatCitation & { opportunity_id?: string | null })
      .opportunity_id ?? scope;
  const isRecord = citation.event_type?.endsWith(".deal.read") ?? false;
  const label = `${isRecord ? "Registro consultado" : (citation.event_type ?? "Evento")} · ${citation.event_id}`;
  return opportunity ? (
    <Link
      to={
        isRecord
          ? `/opportunities/${encodeURIComponent(opportunity)}`
          : `/opportunities/${encodeURIComponent(opportunity)}#event-${encodeURIComponent(citation.event_id)}`
      }
    >
      {label}
    </Link>
  ) : (
    <span>{label}</span>
  );
}

export function ChatEvidence({
  context,
  tools,
  scope,
}: {
  context: ChatContext | null;
  tools: ChatTool[];
  scope?: string;
}) {
  if (!context || (context.source === "Conversa" && tools.length === 0))
    return null;
  return (
    <details className="chat-evidence">
      <summary>Ferramentas e fontes desta resposta</summary>
      <p>
        Fonte: {context.source} · Consulta: {dateTime(context.captured_at)}
      </p>
      {tools.length > 0 ? (
        <ul>
          {tools.map((tool, index) => (
            <li key={index}>
              {toolLabels[tool.name] ?? tool.name}:{" "}
              {tool.status === "running"
                ? "consultando"
                : tool.status === "completed"
                  ? "concluído"
                  : tool.status}
            </li>
          ))}
        </ul>
      ) : null}
      {context.citations.length > 0 ? (
        <ul>
          {context.citations.map((citation) => (
            <li key={citation.event_id}>
              <Citation citation={citation} scope={scope} />
            </li>
          ))}
        </ul>
      ) : (
        <p>Esta resposta não inclui citações de eventos.</p>
      )}
      <details className="chat-technical">
        <summary>Detalhes da consulta</summary>
        <p>
          Identificador do conteúdo: <code>{context.content_hash}</code>
        </p>
        <p>
          {context.tokens_upper_bound} / {context.token_limit} limite superior
          de tokens de evidência.
        </p>
        <p>
          Instruções:{" "}
          {context.instruction_tokens_upper_bound ?? "não informado"} ·
          Pergunta: {context.question_tokens_upper_bound ?? "não informado"}
        </p>
        <p>
          Estimativa conservadora por bytes UTF-8; não é a contagem faturada
          pelo provedor.
        </p>
        {context.truncated ? (
          <p>
            Parte dos dados foi omitida para respeitar o limite de contexto.
          </p>
        ) : null}
        <pre>{context.content}</pre>
      </details>
    </details>
  );
}
