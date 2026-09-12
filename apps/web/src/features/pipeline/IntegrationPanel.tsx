import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  getIntegrationJobs,
  getIntegrationMapping,
  retryIntegrationJob,
  saveIntegrationMapping,
  startIntegrationSync,
} from "./api";
import type { IntegrationMapping } from "./types";

const statusLabels: Record<string, string> = {
  queued: "Na fila",
  running: "Em execução",
  succeeded: "Concluído",
  failed: "Falhou",
  dead: "Interrompido",
  dead_letter: "Interrompido",
  cancelled: "Cancelado",
};

function MappingEditor({ value }: { value: IntegrationMapping }) {
  const client = useQueryClient();
  const [fields, setFields] = useState(
    value.mapping.fields.length ? value.mapping.fields : value.suggested.fields,
  );
  const [stages, setStages] = useState(
    value.mapping.stages.length ? value.mapping.stages : value.suggested.stages,
  );
  const save = useMutation({
    mutationFn: () =>
      saveIntegrationMapping({
        expected_version: value.mapping.version,
        fields,
        stages,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["pipeline"] });
      void client.invalidateQueries({ queryKey: ["integration-mapping"] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <form onSubmit={submit} className="pipeline-mapping">
      <div className="pipeline-section-heading">
        <h3>Contrato de campos e etapas</h3>
        <code>versão {value.mapping.version}</code>
      </div>
      <p>
        A fonte continua sendo o CRM. A ativação valida o contrato no servidor;
        não sobrescreve a massa de testes.
      </p>
      <div className="pipeline-mapping-grid">
        <fieldset disabled={save.isPending}>
          <legend>Campos do provedor → ARES</legend>
          {fields.map((field, index) => (
            <label key={field.canonical_field} className="pipeline-field-row">
              <span>
                {field.canonical_field}
                {field.required ? " *" : ""}
              </span>
              <input
                required={field.required}
                aria-label={`Origem de ${field.canonical_field}`}
                value={field.provider_path}
                onChange={(event) =>
                  setFields((current) =>
                    current.map((entry, position) =>
                      position === index
                        ? { ...entry, provider_path: event.target.value }
                        : entry,
                    ),
                  )
                }
              />
            </label>
          ))}
        </fieldset>
        <fieldset disabled={save.isPending}>
          <legend>Etapas externas → canônicas</legend>
          {stages.map((stage, index) => (
            <label key={stage.canonical_stage} className="pipeline-field-row">
              <span>{stage.label}</span>
              <input
                required
                aria-label={`Etapa externa para ${stage.label}`}
                value={stage.external_stage}
                onChange={(event) =>
                  setStages((current) =>
                    current.map((entry, position) =>
                      position === index
                        ? { ...entry, external_stage: event.target.value }
                        : entry,
                    ),
                  )
                }
              />
            </label>
          ))}
        </fieldset>
      </div>
      {save.error && (
        <p role="alert">
          {save.error.message} Recarregue o contrato se outra pessoa o alterou.
        </p>
      )}
      <Button
        type="submit"
        disabled={save.isPending || !fields.length || !stages.length}
      >
        {save.isPending ? "Validando contrato…" : "Validar e ativar mapeamento"}
      </Button>
    </form>
  );
}

export function IntegrationPanel() {
  const client = useQueryClient();
  const mapping = useQuery({
    queryKey: ["integration-mapping"],
    queryFn: getIntegrationMapping,
  });
  const jobs = useQuery({
    queryKey: ["integration-jobs"],
    queryFn: getIntegrationJobs,
    refetchInterval: 10000,
    refetchIntervalInBackground: false,
  });
  const [months, setMonths] = useState("3");
  const latestJob = jobs.data?.items[0];
  useEffect(() => {
    if (latestJob?.status === "succeeded") {
      void client.invalidateQueries({ queryKey: ["pipeline"] });
    }
  }, [client, latestJob?.id, latestJob?.status]);
  const [notice, setNotice] = useState("");
  const sync = useMutation({
    mutationFn: (mode: "incremental" | "reconcile" | "historical") => {
      const until = new Date();
      const since = new Date(until);
      since.setUTCDate(since.getUTCDate() - Number(months) * 30);
      return startIntegrationSync({
        mode,
        ...(mode === "historical"
          ? { since: since.toISOString(), until: until.toISOString() }
          : {}),
      });
    },
    onSuccess: () => {
      setNotice(
        "Solicitação registrada. O worker processará a carga; acompanhe o estado abaixo.",
      );
      void client.invalidateQueries({ queryKey: ["integration-jobs"] });
    },
  });
  const retry = useMutation({
    mutationFn: retryIntegrationJob,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["integration-jobs"] });
    },
  });
  const active =
    jobs.data?.items.some(
      (job) => job.status === "queued" || job.status === "running",
    ) ?? false;
  return (
    <section
      className="pipeline-integration"
      aria-label="Configuração e sincronização"
    >
      {mapping.isPending && (
        <p role="status">Carregando contrato da integração…</p>
      )}
      {mapping.error && (
        <p role="alert">
          {mapping.error.message}{" "}
          <Button variant="outline" onClick={() => void mapping.refetch()}>
            Recarregar contrato
          </Button>
        </p>
      )}
      {mapping.data && (
        <MappingEditor
          key={mapping.data.mapping.version}
          value={mapping.data}
        />
      )}
      <div className="pipeline-sync-controls">
        <div>
          <h3>Cargas auditáveis</h3>
          <p>
            Incremental retoma o checkpoint. Reconciliação verifica ausências
            sem excluir negócios. Histórico usa uma janela separada de 90 ou 180
            dias.
          </p>
        </div>
        <div className="pipeline-actions">
          <Button
            variant="outline"
            disabled={
              sync.isPending || active || !mapping.data?.mapping.version
            }
            onClick={() => sync.mutate("incremental")}
          >
            Sincronizar alterações
          </Button>
          <Button
            variant="outline"
            disabled={
              sync.isPending || active || !mapping.data?.mapping.version
            }
            onClick={() => sync.mutate("reconcile")}
          >
            Reconciliar funil
          </Button>
          <label className="pipeline-inline-field">
            Histórico
            <select
              value={months}
              onChange={(event) => setMonths(event.target.value)}
            >
              <option value="3">90 dias</option>
              <option value="6">180 dias</option>
            </select>
          </label>
          <Button
            variant="outline"
            disabled={
              sync.isPending || active || !mapping.data?.mapping.version
            }
            onClick={() => sync.mutate("historical")}
          >
            Carregar histórico
          </Button>
        </div>
        {active && (
          <p role="status">
            Há uma carga na fila ou em execução. Novas cargas aguardam sua
            conclusão.
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {(sync.error || retry.error) && (
          <p role="alert">{sync.error?.message ?? retry.error?.message}</p>
        )}
      </div>
      <div className="pipeline-section-heading">
        <h3>Execuções recentes</h3>
        <Button
          variant="ghost"
          onClick={() => void jobs.refetch()}
          disabled={jobs.isFetching}
        >
          Atualizar execuções
        </Button>
      </div>
      {jobs.error && (
        <p role="alert">
          Não foi possível consultar as execuções: {jobs.error.message}
        </p>
      )}
      {jobs.isPending && <p role="status">Consultando worker…</p>}
      {jobs.data?.items.length === 0 && (
        <p>Nenhuma carga solicitada nesta conexão.</p>
      )}
      <ol className="pipeline-jobs">
        {jobs.data?.items.map((job) => (
          <li key={job.id}>
            <div>
              <strong>{statusLabels[job.status] ?? job.status}</strong>
              <span>
                {job.payload.mode ?? "Sincronização"} · {job.attempts}{" "}
                tentativa(s)
              </span>
              <code>{job.id}</code>
            </div>
            <span>
              {job.payload.records ?? 0} registros processados
              {job.error_code ? ` · ${job.error_code}` : ""}
            </span>
            {["failed", "dead", "dead_letter"].includes(job.status) && (
              <Button
                variant="outline"
                disabled={retry.isPending || active}
                onClick={() => retry.mutate(job.id)}
              >
                Retomar carga
              </Button>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
