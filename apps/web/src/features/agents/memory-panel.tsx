import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/auth-context";
import type { DocumentUpload } from "./contract";
import {
  memoryConfiguration,
  memorySaveConfiguration,
  memoryDocuments,
  memoryUpload,
  memoryRemove,
  type MemoryConfiguration,
  type MemoryDocument,
} from "./intelligence-api";
import "./commercial.css";
import "./memory.css";

export function MemoryPanel() {
  const { session } = useAuth();
  const identity = [
    session.user.id,
    session.user.app_metadata.active_tenant_id,
  ];
  const config = useQuery({
    queryKey: ["memory-config", ...identity],
    queryFn: memoryConfiguration,
    retry: false,
  });
  const documents = useQuery({
    queryKey: ["memory-documents", ...identity],
    queryFn: memoryDocuments,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        ["queued", "indexing"].includes(item.status),
      )
        ? 5000
        : false,
  });
  return (
    <section
      className="panel commercial-panel"
      aria-label="Memória comercial e resultados"
    >
      <header>
        <div>
          <span className="eyebrow">FONTES AUTORIZADAS</span>
          <h2>Memória comercial e resultados</h2>
          <p>
            Playbooks da empresa com fonte e versão. A avaliação usa resultados
            registrados, sem presumir causalidade.
          </p>
        </div>
      </header>
      {config.isPending ? (
        <p role="status">Carregando memória…</p>
      ) : config.isError ? (
        <p role="alert">
          Não foi possível ler a configuração.{" "}
          <Button onClick={() => void config.refetch()}>
            Tentar novamente
          </Button>
        </p>
      ) : config.data ? (
        <MemorySettings
          key={`settings-${config.data.configuration.version}`}
          data={config.data}
        />
      ) : null}
      {config.data?.can_configure ? (
        <MemoryUploadForm
          key={`upload-${config.data.configuration.version}`}
          disabled={!config.data.configuration.enabled}
          documents={documents.data?.items ?? []}
        />
      ) : null}
      <h3>Documentos e versões</h3>
      {documents.isPending ? (
        <p role="status">Carregando documentos…</p>
      ) : documents.isError ? (
        <p role="alert">
          Não foi possível carregar documentos.{" "}
          <Button onClick={() => void documents.refetch()}>
            Recarregar documentos
          </Button>
        </p>
      ) : !documents.data?.items.length ? (
        <p>
          Nenhum documento autorizado. TXT e Markdown, até 256 KiB por arquivo.
        </p>
      ) : (
        <ul className="memory-documents">
          {documents.data.items.map((document) => (
            <MemoryDocumentRow
              key={document.id}
              document={document}
              canConfigure={!!config.data?.can_configure}
            />
          ))}
        </ul>
      )}
      <footer>
        Conteúdo original armazenado no banco privado. PDF, DOCX, OCR e
        código-fonte não são formatos suportados. A empresa deve revisar e
        remover dados pessoais antes do envio.
      </footer>
    </section>
  );
}

function MemorySettings({ data }: { data: MemoryConfiguration }) {
  const client = useQueryClient();
  const [config, setConfig] = useState(data.configuration);
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: memorySaveConfiguration,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["memory-config"] });
      void client.invalidateQueries({ queryKey: ["outcome"] });
    },
  });
  const fields = [
    ["enabled", "Ativar memória comercial"],
    [
      "external_consent",
      "Autorizar envio de documentos e perguntas à OpenAI para embeddings",
    ],
    ["outcomes_enabled", "Ativar agente de avaliação de resultados"],
    ["episodes_enabled", "Permitir publicação manual de episódios verificados"],
  ] as const;
  return (
    <details className="memory-settings">
      <summary>Configuração e processamento de dados</summary>
      <p>{data.processing}</p>
      <p>
        Armazenamento: {Math.round(data.limits.memory_storage_bytes / 1048576)}{" "}
        MiB. Indexação: R$ {data.limits.embedding_daily_budget_brl}/dia. Limites
        contratados são administrados na Central Admin.
      </p>
      <form
        className="commercial-form"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate({
            expected_version: config.version,
            enabled: config.enabled,
            external_consent: config.external_consent,
            outcomes_enabled: config.outcomes_enabled,
            episodes_enabled: config.episodes_enabled,
            observation_hours: config.observation_hours,
            retention_days: config.retention_days,
            reason,
          });
        }}
      >
        <fieldset disabled={!data.can_configure || mutation.isPending}>
          <legend>Controles da empresa</legend>
          {fields.map(([key, label]) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={!!config[key]}
                onChange={(e) =>
                  setConfig({ ...config, [key]: e.target.checked })
                }
              />
              {label}
            </label>
          ))}
          <label>
            Janela de observação (horas)
            <input
              type="number"
              min={1}
              max={720}
              value={config.observation_hours}
              onChange={(e) =>
                setConfig({
                  ...config,
                  observation_hours: Number(e.target.value),
                })
              }
            />
          </label>
          <label>
            Retenção máxima (dias)
            <input
              type="number"
              min={1}
              max={365}
              value={config.retention_days}
              onChange={(e) =>
                setConfig({ ...config, retention_days: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Justificativa da configuração
            <input
              required
              minLength={8}
              maxLength={300}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          {data.can_configure ? (
            <Button type="submit">
              {mutation.isPending ? "Salvando…" : "Salvar configuração"}
            </Button>
          ) : (
            <p>Somente o administrador da empresa pode configurar.</p>
          )}
        </fieldset>
      </form>
      {mutation.isError ? (
        <p role="alert">{mutation.error.message}</p>
      ) : mutation.isSuccess ? (
        <p role="status">Configuração salva.</p>
      ) : null}
    </details>
  );
}

function MemoryUploadForm({
  disabled,
  documents,
}: {
  disabled: boolean;
  documents: MemoryDocument[];
}) {
  const client = useQueryClient();
  const [documentId, setDocumentId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: memoryUpload,
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["memory-documents"] }),
  });
  return (
    <details className="memory-settings">
      <summary>Adicionar ou atualizar documento</summary>
      <form
        className="commercial-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          const form = new FormData(e.currentTarget);
          if (!file || file.size > 262144 || !/\.(txt|md)$/i.test(file.name)) {
            setError("Selecione TXT ou Markdown com até 256 KiB.");
            return;
          }
          try {
            const buffer = await file.arrayBuffer();
            const content = new TextDecoder("utf-8", { fatal: true }).decode(
              buffer,
            );
            const previous = documents.find((item) => item.id === documentId);
            const roles = form
              .getAll("roles")
              .map(String) as DocumentUpload["allowed_roles"];
            const purposes = form
              .getAll("purposes")
              .map(String) as DocumentUpload["purposes"];
            mutation.mutate({
              filename: file.name,
              title: String(form.get("title")),
              source_label: String(form.get("source")),
              content,
              verified_source: true,
              reason: String(form.get("reason")),
              document_id: documentId || null,
              expected_version: previous?.current_version ?? 0,
              allowed_roles: roles,
              purposes,
              owner_user_id: String(form.get("owner")) || null,
              validity_days: Number(form.get("validity")),
              classification:
                form.get("classification") === "restricted"
                  ? "restricted"
                  : "internal",
            });
          } catch {
            setError("Arquivo inválido: utilize texto UTF-8.");
          }
        }}
      >
        <fieldset disabled={disabled || mutation.isPending}>
          <legend>Fonte revisada pela empresa</legend>
          <label>
            Documento
            <select
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
            >
              <option value="">Novo documento</option>
              {documents.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title} · v{item.current_version}
                </option>
              ))}
            </select>
          </label>
          <label>
            Arquivo TXT ou Markdown
            <input
              required
              type="file"
              accept=".txt,.md,text/plain,text/markdown"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <label>
            Título
            <input name="title" required minLength={3} maxLength={160} />
          </label>
          <label>
            Fonte original
            <input name="source" required minLength={3} maxLength={200} />
          </label>
          <label>
            Classificação
            <select name="classification">
              <option value="internal">Interno</option>
              <option value="restricted">Restrito</option>
            </select>
          </label>
          <label>
            Validade (dias)
            <input
              name="validity"
              type="number"
              required
              min={1}
              max={365}
              defaultValue={90}
            />
          </label>
          <label>
            Usuário da carteira (UUID; obrigatório para vendedores)
            <input name="owner" pattern="[0-9a-fA-F-]{36}" />
          </label>
          <div className="memory-checkboxes">
            <strong>Papéis autorizados</strong>
            {(["admin", "manager", "seller", "auditor"] as const).map(
              (role) => (
                <label key={role}>
                  <input
                    type="checkbox"
                    name="roles"
                    value={role}
                    defaultChecked={role === "admin" || role === "manager"}
                  />
                  {
                    {
                      admin: "Administrador",
                      manager: "Gestor",
                      seller: "Vendedor",
                      auditor: "Auditor",
                    }[role]
                  }
                </label>
              ),
            )}
          </div>
          <div className="memory-checkboxes">
            <strong>Finalidades autorizadas</strong>
            {(
              [
                "chat",
                "diagnosis",
                "recommendation",
                "sentinel",
                "portfolio",
                "outcome",
              ] as const
            ).map((purpose) => (
              <label key={purpose}>
                <input
                  type="checkbox"
                  name="purposes"
                  value={purpose}
                  defaultChecked={purpose === "chat"}
                />
                {
                  {
                    chat: "Chat",
                    diagnosis: "Diagnóstico",
                    recommendation: "Recomendação",
                    sentinel: "Sentinela",
                    portfolio: "Carteira",
                    outcome: "Resultados",
                  }[purpose]
                }
              </label>
            ))}
          </div>
          <label>
            Justificativa do envio
            <input name="reason" required minLength={8} maxLength={300} />
          </label>
          <label>
            <input type="checkbox" required />
            Revisei a fonte e removi segredos e dados pessoais desnecessários.
          </label>
          <Button type="submit">
            {mutation.isPending ? "Enviando…" : "Salvar documento"}
          </Button>
        </fieldset>
      </form>
      {disabled ? <p>Ative a memória para enviar documentos.</p> : null}
      {error || mutation.isError ? (
        <p role="alert">{error || mutation.error?.message}</p>
      ) : mutation.isSuccess ? (
        <p role="status">
          Documento salvo; indexação na fila. Atualize a lista para conferir.
        </p>
      ) : null}
    </details>
  );
}

function MemoryDocumentRow({
  document,
  canConfigure,
}: {
  document: MemoryDocument;
  canConfigure: boolean;
}) {
  const client = useQueryClient();
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: () => memoryRemove(document.id, reason),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["memory-documents"] }),
  });
  return (
    <li>
      <strong>{document.title}</strong>
      <p>
        {document.source_label} · versão {document.current_version} ·{" "}
        {(
          {
            queued: "Na fila",
            indexing: "Indexando",
            ready: "Busca híbrida",
            lexical_only: "Busca textual local",
            failed: "Falha",
            deleted: "Expirado",
          } as Record<string, string>
        )[document.status] ?? document.status}
      </p>
      <small>
        Validade: {new Date(document.expires_at).toLocaleDateString("pt-BR")} ·
        Papéis: {document.allowed_roles.join(", ")} · Finalidades:{" "}
        {document.purposes.join(", ")}
      </small>
      {document.error_code ? (
        <p role="alert">Indexação indisponível: {document.error_code}</p>
      ) : null}
      {canConfigure ? (
        <details>
          <summary>Remover documento</summary>
          <form
            className="commercial-controls"
            onSubmit={(e) => {
              e.preventDefault();
              mutation.mutate();
            }}
          >
            <label>
              Justificativa da remoção
              <input
                required
                minLength={8}
                maxLength={300}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <Button type="submit" disabled={mutation.isPending}>
              Remover fonte e trechos
            </Button>
          </form>
        </details>
      ) : null}
      {mutation.isError ? <p role="alert">{mutation.error.message}</p> : null}
    </li>
  );
}
