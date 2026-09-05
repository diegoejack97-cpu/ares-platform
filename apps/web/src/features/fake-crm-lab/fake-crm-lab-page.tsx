import { useDeferredValue, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowClockwiseIcon,
  ArrowSquareOutIcon,
  CheckCircleIcon,
  FlaskIcon,
  MagnifyingGlassIcon,
  NotePencilIcon,
  PulseIcon,
  SelectionForegroundIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { safeSum } from "@/lib/numbers";
import { money } from "@/features/opportunities/format";
import { Freshness } from "@/components/live/freshness";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  addFakeCRMNote,
  createFakeCRMTask,
  getFakeCRMLabSnapshot,
  resetFakeCRMLab,
  sendFakeCRMEvent,
  testFakeCRMFault,
  updateFakeCRMStage,
} from "./api";
import type { FakeCRMDeal, FakeCRMFaultResult } from "./types";

const scenarioLabels: Record<string, string> = {
  follow_up_overdue: "Follow-up vencido",
  proposal_stalled: "Proposta parada",
  no_owner: "Sem responsável",
  customer_replied: "Cliente respondeu",
  duplicate_candidate: "Possível duplicata",
  healthy_pipeline: "Funil saudável",
  won_after_intervention: "Venda após intervenção",
  lost_no_response: "Perdida sem resposta",
};
const faultLabels: Record<string, string> = {
  unauthorized: "401 credencial",
  not_found: "404 ausente",
  conflict: "409 conflito",
  rate_limit: "429 limite",
  server_error: "500 provedor",
  timeout: "Timeout",
};

type LabCommand =
  | { kind: "task"; dealId: string; title: string }
  | { kind: "note"; dealId: string; body: string }
  | { kind: "stage"; dealId: string; stage: string; version: number }
  | { kind: "event"; dealId: string }
  | { kind: "fault"; scenario: string };

interface OperationState {
  tone: "success" | "warning";
  title: string;
  detail: string;
}

function executeCommand(command: LabCommand): Promise<unknown> {
  switch (command.kind) {
    case "task":
      return createFakeCRMTask(command.dealId, command.title);
    case "note":
      return addFakeCRMNote(command.dealId, command.body);
    case "stage":
      return updateFakeCRMStage(command.dealId, command.stage, command.version);
    case "event":
      return sendFakeCRMEvent(command.dealId);
    case "fault":
      return testFakeCRMFault(command.scenario);
  }
}

function getSuccessState(command: LabCommand, result: unknown): OperationState {
  if (command.kind === "fault") {
    const fault = result as FakeCRMFaultResult;
    return {
      tone: fault.observed ? "warning" : "success",
      title: fault.observed
        ? "Falha observada e classificada"
        : "Falha não observada",
      detail: `${faultLabels[fault.scenario] ?? fault.scenario}: ${fault.code}${
        fault.retry_after ? ` · Retry-After ${fault.retry_after}s` : ""
      }`,
    };
  }
  const labels = {
    task: "Tarefa criada no sandbox",
    note: "Nota registrada no sandbox",
    stage: "Etapa atualizada com controle de versão",
    event: "Evento enviado ao ARES e registrado no Journal",
  } as const;
  return {
    tone: "success",
    title: labels[command.kind],
    detail: `Negócio ${command.dealId} · operação sintética auditável`,
  };
}

function stageSummary(deals: FakeCRMDeal[], stages: string[]) {
  return stages.map((stage) => {
    const matches = deals.filter((deal) => deal.stage === stage);
    return {
      stage,
      count: matches.length,
      ...safeSum(matches, "value"),
    };
  });
}

export function FakeCRMLabPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [scenario, setScenario] = useState("all");
  const [operation, setOperation] = useState<OperationState | null>(null);
  const deferredSearch = useDeferredValue(
    search.trim().toLocaleLowerCase("pt-BR"),
  );
  const snapshotQuery = useQuery({
    queryKey: ["fake-crm-lab"],
    queryFn: getFakeCRMLabSnapshot,
    refetchInterval: 15_000,
  });
  const resetMutation = useMutation({
    mutationFn: resetFakeCRMLab,
    onSuccess: async () => {
      setSelectedId(null);
      setOperation({
        tone: "success",
        title: "Massa sintética restaurada",
        detail: "IDs, cenários e versões voltaram ao estado determinístico.",
      });
      await queryClient.invalidateQueries({ queryKey: ["fake-crm-lab"] });
    },
    onError: (error) =>
      setOperation({
        tone: "warning",
        title: "Reset não concluído",
        detail: error instanceof Error ? error.message : "Erro desconhecido",
      }),
  });
  const commandMutation = useMutation({
    mutationFn: executeCommand,
    onSuccess: async (result, command) => {
      setOperation(getSuccessState(command, result));
      if (command.kind !== "fault" && command.kind !== "event") {
        await queryClient.invalidateQueries({ queryKey: ["fake-crm-lab"] });
      }
    },
    onError: (error) =>
      setOperation({
        tone: "warning",
        title: "Operação recusada",
        detail: error instanceof Error ? error.message : "Erro desconhecido",
      }),
  });

  const snapshot = snapshotQuery.data;
  const snapshotErrorMessage =
    snapshotQuery.error instanceof Error ? snapshotQuery.error.message : "";
  const isPermissionDenied = snapshotErrorMessage.includes("admin_required");
  const selectedDeal =
    snapshot?.deals.find((deal) => deal.id === selectedId) ??
    snapshot?.deals[0];
  const filteredDeals =
    snapshot?.deals.filter((deal) => {
      const matchesSearch =
        !deferredSearch ||
        `${deal.title} ${deal.id} ${deal.owner_id ?? ""}`
          .toLocaleLowerCase("pt-BR")
          .includes(deferredSearch);
      const matchesScenario = scenario === "all" || deal.scenario === scenario;
      return matchesSearch && matchesScenario;
    }) ?? [];
  const pipeline = snapshot
    ? stageSummary(
        snapshot.deals,
        snapshot.stages.map((stage) => stage.id),
      )
    : [];

  function submitText(
    event: FormEvent<HTMLFormElement>,
    kind: "task" | "note",
  ) {
    event.preventDefault();
    if (!selectedDeal) return;
    const form = new FormData(event.currentTarget);
    const content = String(form.get("content") ?? "").trim();
    if (!content) return;
    commandMutation.mutate(
      kind === "task"
        ? { kind, dealId: selectedDeal.id, title: content }
        : { kind, dealId: selectedDeal.id, body: content },
    );
  }

  function submitStage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDeal) return;
    const stage = String(new FormData(event.currentTarget).get("stage") ?? "");
    commandMutation.mutate({
      kind: "stage",
      dealId: selectedDeal.id,
      stage,
      version: selectedDeal.version,
    });
  }

  return (
    <main className="workspace fake-lab-page">
      <header className="page-header fake-lab-header">
        <div>
          <span className="eyebrow">ARES CONNECT / INTEGRAÇÃO CONTROLADA</span>
          <h1>Laboratório FakeCRM</h1>
          <p>
            Bancada visual para exercitar o contrato do ARES Connect com dados
            explicitamente sintéticos. Não é o CRM oficial do cliente.
          </p>
        </div>
        <div className="lab-header-actions">
          <Button variant="outline" asChild>
            <a
              href="http://127.0.0.1:8010/docs"
              target="_blank"
              rel="noreferrer"
            >
              <ArrowSquareOutIcon aria-hidden /> Abrir contrato HTTP
            </a>
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => resetMutation.mutate()}
            disabled={resetMutation.isPending}
          >
            <ArrowClockwiseIcon
              className={resetMutation.isPending ? "animate-spin" : undefined}
              aria-hidden
            />
            Restaurar massa
          </Button>
        </div>
      </header>

      {snapshotQuery.isLoading ? (
        <LabSkeleton />
      ) : !snapshot ? (
        <section className="panel lab-unavailable" role="alert">
          <WarningCircleIcon size={30} weight="fill" aria-hidden />
          <div>
            <strong>
              {isPermissionDenied ? "Acesso restrito" : "Sandbox indisponível"}
            </strong>
            <p>
              {isPermissionDenied
                ? "O Laboratório FakeCRM é uma ferramenta de desenvolvimento disponível somente para administradores."
                : "Confirme os processos ARES API em 8000 e FakeCRM em 8010. Nenhum dado foi inventado para preencher esta tela."}
            </p>
          </div>
          <Button variant="outline" onClick={() => snapshotQuery.refetch()}>
            Tentar novamente
          </Button>
        </section>
      ) : (
        <>
          <section
            className="lab-status-rail"
            aria-label="Estado do FakeCRM Sandbox"
          >
            <div>
              <span>Serviço</span>
              <strong className="lab-online">
                <CheckCircleIcon weight="fill" aria-hidden />{" "}
                {snapshot.health.status}
              </strong>
              <small>porta 8010 · HTTP</small>
            </div>
            <div>
              <span>Massa ativa</span>
              <strong className="tabular">
                {snapshot.counts.deals} negócios
              </strong>
              <small>{snapshot.counts.activities} atividades sintéticas</small>
            </div>
            <div>
              <span>Escritas de teste</span>
              <strong className="tabular">
                {snapshot.counts.tasks} tarefas · {snapshot.counts.notes} notas
              </strong>
              <small>resetáveis e sem PII real</small>
            </div>
            <div>
              <span>Frescor</span>
              <strong className="tabular">
                <Freshness timestamp={snapshotQuery.dataUpdatedAt} />
              </strong>
              <small>{snapshot.source}</small>
            </div>
          </section>

          <section
            className="panel lab-pipeline"
            aria-labelledby="pipeline-title"
          >
            <div className="panel-heading">
              <div>
                <h2 id="pipeline-title">Leitura do funil sintético</h2>
                <p>Contagem e valor observado por etapa · moeda BRL</p>
              </div>
              <Badge variant="outline">watermark ativo</Badge>
            </div>
            <div className="lab-stage-grid">
              {pipeline.map((item, index) => (
                <div key={item.stage} className="lab-stage-cell">
                  <span className="lab-stage-index">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <strong>
                    {
                      snapshot.stages.find((stage) => stage.id === item.stage)
                        ?.label
                    }
                  </strong>
                  <b className="tabular">{item.count} negócios</b>
                  <small className="tabular">
                    {item.valid ? money(item.total) : "Valor não informado"}
                    {item.partial ? ` · ${item.missing} valores ausentes` : ""}
                  </small>
                </div>
              ))}
            </div>
            <p className="provenance">
              Fonte {snapshot.source}. Valores servem somente para teste; não
              são receita real, influência do ARES ou resultado incremental.
            </p>
          </section>

          <div className="lab-workbench">
            <section className="panel lab-deals" aria-labelledby="deals-title">
              <div className="panel-heading lab-toolbar">
                <div>
                  <h2 id="deals-title">Oportunidades de ensaio</h2>
                  <p>
                    {filteredDeals.length} de {snapshot.deals.length} registros
                  </p>
                </div>
                <div className="lab-filters">
                  <label>
                    <span>Buscar</span>
                    <Input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="ID, título ou responsável"
                    />
                  </label>
                  <label>
                    <span>Cenário</span>
                    <select
                      value={scenario}
                      onChange={(event) => setScenario(event.target.value)}
                    >
                      <option value="all">Todos</option>
                      {Object.entries(scenarioLabels).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
              <div className="lab-table-wrap">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Selecionar</TableHead>
                      <TableHead>Negócio</TableHead>
                      <TableHead>Cenário</TableHead>
                      <TableHead>Etapa</TableHead>
                      <TableHead>Valor</TableHead>
                      <TableHead>Versão</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredDeals.slice(0, 20).map((deal) => (
                      <TableRow
                        key={deal.id}
                        data-selected={
                          selectedDeal?.id === deal.id ? "true" : undefined
                        }
                      >
                        <TableCell>
                          <button
                            className="lab-select-deal"
                            type="button"
                            aria-label={`Selecionar ${deal.title}`}
                            aria-pressed={selectedDeal?.id === deal.id}
                            onClick={() => setSelectedId(deal.id)}
                          >
                            <SelectionForegroundIcon
                              weight="bold"
                              aria-hidden
                            />
                          </button>
                        </TableCell>
                        <TableCell>
                          <strong>{deal.title}</strong>
                          <small>
                            {deal.id} · {deal.owner_id ?? "sem responsável"}
                          </small>
                        </TableCell>
                        <TableCell>
                          <span
                            className={`lab-scenario scenario-${deal.scenario}`}
                          >
                            {scenarioLabels[deal.scenario] ?? deal.scenario}
                          </span>
                        </TableCell>
                        <TableCell>{deal.stage}</TableCell>
                        <TableCell className="tabular">
                          {money(deal.value)}
                        </TableCell>
                        <TableCell>
                          <code>v{deal.version}</code>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {filteredDeals.length === 0 ? (
                <div className="lab-empty-results" role="status">
                  <MagnifyingGlassIcon size={22} aria-hidden />
                  <strong>Nenhum cenário encontrado</strong>
                  <span>Ajuste a busca ou selecione outro cenário.</span>
                </div>
              ) : null}
              {filteredDeals.length > 20 ? (
                <p className="lab-table-limit">
                  Exibindo 20 registros. Use os filtros para localizar os
                  demais.
                </p>
              ) : null}
            </section>

            <aside className="lab-side-column">
              {selectedDeal ? (
                <section
                  className="panel lab-selected"
                  aria-labelledby="selected-title"
                >
                  <div className="panel-heading">
                    <div>
                      <h2 id="selected-title">Bancada de operações</h2>
                      <p>
                        {selectedDeal.id} · versão {selectedDeal.version}
                      </p>
                    </div>
                    <FlaskIcon size={22} aria-hidden />
                  </div>
                  <div className="lab-selected-summary">
                    <span>Negócio selecionado</span>
                    <strong>{selectedDeal.title}</strong>
                    <small>{scenarioLabels[selectedDeal.scenario]}</small>
                  </div>
                  <div className="lab-operation-stack">
                    <Button
                      type="button"
                      onClick={() =>
                        commandMutation.mutate({
                          kind: "event",
                          dealId: selectedDeal.id,
                        })
                      }
                      disabled={commandMutation.isPending}
                    >
                      <PulseIcon weight="bold" aria-hidden /> Enviar evento ao
                      ARES
                    </Button>
                    <form onSubmit={(event) => submitText(event, "task")}>
                      <label htmlFor="lab-task">Criar tarefa</label>
                      <div>
                        <Input
                          id="lab-task"
                          name="content"
                          defaultValue="Retomar oportunidade sintética"
                        />
                        <Button
                          type="submit"
                          variant="outline"
                          disabled={
                            commandMutation.isPending ||
                            !snapshot.capabilities.create_task
                          }
                        >
                          Criar
                        </Button>
                      </div>
                    </form>
                    <form onSubmit={(event) => submitText(event, "note")}>
                      <label htmlFor="lab-note">Adicionar nota</label>
                      <div>
                        <Input
                          id="lab-note"
                          name="content"
                          defaultValue="Registro de teste sem dados pessoais"
                        />
                        <Button
                          type="submit"
                          variant="outline"
                          disabled={
                            commandMutation.isPending ||
                            !snapshot.capabilities.add_note
                          }
                        >
                          <NotePencilIcon aria-hidden /> Salvar
                        </Button>
                      </div>
                    </form>
                    <form key={selectedDeal.id} onSubmit={submitStage}>
                      <label htmlFor="lab-stage">
                        Alterar etapa com versão esperada
                      </label>
                      <div>
                        <select
                          id="lab-stage"
                          name="stage"
                          defaultValue={selectedDeal.stage}
                        >
                          {snapshot.stages.map((stage) => (
                            <option key={stage.id} value={stage.id}>
                              {stage.label}
                            </option>
                          ))}
                        </select>
                        <Button
                          type="submit"
                          variant="outline"
                          disabled={
                            commandMutation.isPending ||
                            !snapshot.capabilities.update_stage
                          }
                        >
                          Atualizar
                        </Button>
                      </div>
                    </form>
                  </div>
                  {!snapshot.capabilities.create_task ||
                  !snapshot.capabilities.add_note ||
                  !snapshot.capabilities.update_stage ? (
                    <p className="lab-capability-note" role="note">
                      Uma ou mais operações estão desabilitadas porque o
                      provedor não declarou a capability correspondente.
                    </p>
                  ) : null}
                </section>
              ) : null}

              <section
                className="panel lab-faults"
                aria-labelledby="faults-title"
              >
                <div className="panel-heading">
                  <div>
                    <h2 id="faults-title">Mesa de falhas</h2>
                    <p>Respostas controladas do provedor</p>
                  </div>
                  <WarningCircleIcon size={22} aria-hidden />
                </div>
                <div className="lab-fault-grid">
                  {Object.entries(faultLabels).map(([value, label]) => (
                    <Button
                      key={value}
                      type="button"
                      variant="outline"
                      onClick={() =>
                        commandMutation.mutate({
                          kind: "fault",
                          scenario: value,
                        })
                      }
                      disabled={commandMutation.isPending}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
                <p className="contract-note">
                  A falha é observada e classificada; não altera dados nem
                  dispara retry cego de escrita.
                </p>
              </section>

              {operation ? (
                <section
                  className={`lab-operation-result ${operation.tone}`}
                  role="status"
                >
                  {operation.tone === "success" ? (
                    <CheckCircleIcon weight="fill" aria-hidden />
                  ) : (
                    <WarningCircleIcon weight="fill" aria-hidden />
                  )}
                  <div>
                    <strong>{operation.title}</strong>
                    <span>{operation.detail}</span>
                  </div>
                </section>
              ) : null}
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

function LabSkeleton() {
  return (
    <div className="lab-skeleton" aria-label="Carregando Laboratório FakeCRM">
      <Skeleton className="h-24 w-full rounded-none" />
      <Skeleton className="h-40 w-full rounded-none" />
      <div>
        <Skeleton className="h-[420px] w-full rounded-none" />
        <Skeleton className="h-[420px] w-full rounded-none" />
      </div>
    </div>
  );
}
