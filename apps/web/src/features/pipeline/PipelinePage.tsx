import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  ArrowsClockwiseIcon,
  DotsSixVerticalIcon,
  ShieldCheckIcon,
} from "@phosphor-icons/react";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { Dialog } from "radix-ui";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { getPipeline, movePipelineDeal, PipelineError } from "./api";
import { IntegrationPanel } from "./IntegrationPanel";
import type { PipelineDeal, PipelineSnapshot, StageCommand } from "./types";
import "./pipeline.css";

export function formatPipelineValue(
  value: number | null,
  currency: string | null,
) {
  if (value === null) return "Valor não informado";
  if (!currency)
    return `${new Intl.NumberFormat("pt-BR").format(value)} · moeda não informada`;
  try {
    return new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency,
    }).format(value);
  } catch {
    return `${new Intl.NumberFormat("pt-BR").format(value)} ${currency}`;
  }
}

function StageColumn({
  id,
  label,
  count,
  children,
}: {
  id: string;
  label: string;
  count: number;
  children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id, data: { stage: id } });
  return (
    <section
      ref={setNodeRef}
      className="pipeline-column"
      data-over={isOver}
      aria-label={`Etapa ${label}`}
    >
      <header>
        <h2>{label}</h2>
        <span aria-label={`${count} negócios carregados`}>
          {count.toString().padStart(2, "0")}
        </span>
      </header>
      <div className="pipeline-column-body">
        {children}
        {!count && (
          <p className="pipeline-empty-column">Sem negócios neste recorte</p>
        )}
      </div>
    </section>
  );
}

function DealCard({
  deal,
  stages,
  canMove,
  onMove,
}: {
  deal: PipelineDeal;
  stages: PipelineSnapshot["stages"];
  canMove: boolean;
  onMove: (deal: PipelineDeal, stage: string) => void;
}) {
  const allowed = canMove && !deal.is_missing;
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    isDragging,
  } = useDraggable({ id: deal.id, data: { deal }, disabled: !allowed });
  return (
    <article
      ref={setNodeRef}
      className="pipeline-deal"
      data-dragging={isDragging}
      style={
        transform
          ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
          : undefined
      }
    >
      <div className="pipeline-deal-meta">
        <code>{deal.external_id}</code>
        {allowed && (
          <button
            ref={setActivatorNodeRef}
            className="pipeline-drag-handle"
            {...attributes}
            {...listeners}
            aria-label={`Arrastar ${deal.title}`}
          >
            <DotsSixVerticalIcon aria-hidden="true" size={18} />
          </button>
        )}
      </div>
      <h3>{deal.title}</h3>
      <strong className="pipeline-deal-value">
        {formatPipelineValue(deal.value, deal.currency)}
      </strong>
      <div className="pipeline-deal-facts">
        <span>{deal.owner_id ?? "Sem responsável"}</span>
        <span>v{deal.version}</span>
      </div>
      {deal.synthetic && (
        <span className="pipeline-provenance">Dado sintético · FakeCRM</span>
      )}
      {deal.is_missing && (
        <p className="pipeline-deal-warning">
          Ausente na última reconciliação. Mantido para auditoria.
        </p>
      )}
      {allowed && (
        <label className="pipeline-stage-select">
          <span>Mover para</span>
          <select
            aria-label={`Mover ${deal.title} para`}
            value=""
            onChange={(event) => {
              if (event.target.value) onMove(deal, event.target.value);
            }}
          >
            <option value="">Selecionar etapa</option>
            {stages
              .filter((stage) => stage.id !== deal.stage)
              .map((stage) => (
                <option key={stage.id} value={stage.id}>
                  {stage.label}
                </option>
              ))}
          </select>
        </label>
      )}
    </article>
  );
}

interface MoveIntent {
  deal: PipelineDeal;
  command: StageCommand;
}

export function PipelinePage() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const clock = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(clock);
  }, []);
  const client = useQueryClient();
  const [showIntegration, setShowIntegration] = useState(false);
  const [intent, setIntent] = useState<MoveIntent | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const pipeline = useInfiniteQuery({
    queryKey: ["pipeline"],
    queryFn: ({ pageParam }) => getPipeline(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: intent ? false : 15000,
    refetchIntervalInBackground: false,
  });
  const move = useMutation({
    mutationFn: (value: MoveIntent) =>
      movePipelineDeal(value.deal.id, value.command),
    onSuccess: (result) => {
      if (result.status && !["succeeded", "success"].includes(result.status)) {
        setNotice(
          "O CRM ainda não confirmou a mudança. Consulte novamente usando o mesmo intento.",
        );
        return;
      }
      setNotice(
        `Mudança confirmada pelo CRM.${result.duplicate ? " Intenção já processada; nenhuma duplicação." : ""}${result.correlation_id ? ` Correlação: ${result.correlation_id}` : ""}`,
      );
      setDialogOpen(false);
      setIntent(null);
      void client.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });
  const data = pipeline.data?.pages[0];
  const items = [
    ...new Map(
      pipeline.data?.pages
        .flatMap((page) => page.items)
        .map((deal) => [deal.id, deal]) ?? [],
    ).values(),
  ];
  const canMove = Boolean(
    data?.capabilities.update_stage && data.permissions.can_move && !intent,
  );
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor),
  );
  function propose(deal: PipelineDeal, stage: string) {
    if (!canMove || deal.stage === stage || deal.is_missing || intent) return;
    move.reset();
    setNotice("");
    setIntent({
      deal,
      command: {
        stage,
        expected_version: deal.version,
        idempotency_key: crypto.randomUUID(),
        confirmed: true,
      },
    });
    setDialogOpen(true);
  }
  function dragEnd(event: DragEndEvent) {
    const deal = items.find((item) => item.id === event.active.id);
    const stage = event.over?.data.current?.stage as string | undefined;
    if (deal && stage) propose(deal, stage);
  }
  const conflict =
    move.error instanceof PipelineError && move.error.status === 409;
  const blocked =
    move.error instanceof PipelineError &&
    [400, 401, 403, 404, 422].includes(move.error.status);
  const uncertain = Boolean(move.error && !conflict && !blocked);
  const unresolved = Boolean(
    uncertain ||
    (move.isSuccess &&
      move.data?.status &&
      !["succeeded", "success"].includes(move.data.status)),
  );
  function closeDialog() {
    if (move.isPending) return;
    setDialogOpen(false);
    if (!unresolved) {
      setIntent(null);
      move.reset();
    }
  }
  const stale = Boolean(
    data?.freshness_at && now - Date.parse(data.freshness_at) > 300000,
  );
  return (
    <div className="workspace pipeline-workspace">
      <header className="pipeline-page-header">
        <div>
          <p className="pipeline-eyebrow">ARES CONNECT / ESPELHO OPERACIONAL</p>
          <h1>
            Funil CRM <span>/</span>
          </h1>
          <p>
            O negócio permanece no CRM. Cada mudança, confirmada e rastreável.
          </p>
        </div>
        <div className="pipeline-actions">
          <Button
            variant="outline"
            disabled={pipeline.isFetching}
            onClick={() => void pipeline.refetch()}
          >
            <ArrowsClockwiseIcon aria-hidden="true" />
            {pipeline.isFetching ? "Consultando…" : "Atualizar leitura"}
          </Button>
          {data?.permissions.can_manage && (
            <Button
              variant="outline"
              aria-expanded={showIntegration}
              onClick={() => setShowIntegration((value) => !value)}
            >
              {showIntegration ? "Fechar integração" : "Integração e cargas"}
            </Button>
          )}
        </div>
      </header>
      <div className="pipeline-reading-strip">
        <div>
          <span>Negócios carregados</span>
          <strong>{data ? items.length : "—"}</strong>
        </div>
        <div>
          <span>Fonte</span>
          <strong>{data?.source ?? "Aguardando conexão"}</strong>
        </div>
        <div>
          <span>Última sincronização concluída</span>
          <strong>
            {data?.freshness_at
              ? new Date(data.freshness_at).toLocaleString("pt-BR")
              : "Ainda não realizada"}
          </strong>
        </div>
        <div>
          <span>Autoridade do funil</span>
          <strong>CRM externo</strong>
        </div>
      </div>
      {notice && (
        <p className="pipeline-notice" role="status">
          {notice}
        </p>
      )}
      {intent && unresolved && !dialogOpen && (
        <div className="pipeline-alert" role="status">
          <strong>Mudança ainda não confirmada pelo CRM</strong>
          <p>
            Fechar a janela não cancela uma operação já enviada. Consulte o
            mesmo intento antes de solicitar outra mudança.
          </p>
          <Button variant="outline" onClick={() => setDialogOpen(true)}>
            Consultar intento pendente
          </Button>
        </div>
      )}
      {pipeline.error && (
        <div className="pipeline-alert" role="alert">
          <strong>Não foi possível atualizar o funil.</strong>
          <p>
            {pipeline.error.message}{" "}
            {data
              ? "A leitura anterior permanece visível e pode estar desatualizada."
              : "Verifique a API e a conexão configurada."}
          </p>
          <Button variant="outline" onClick={() => void pipeline.refetch()}>
            Tentar novamente
          </Button>
        </div>
      )}
      {pipeline.isPending && (
        <div
          className="pipeline-loading"
          role="status"
          aria-label="Carregando funil"
        >
          <span />
          <span />
          <span />
        </div>
      )}
      {data && (
        <>
          {(stale ||
            data.partial ||
            data.connection?.status === "degraded") && (
            <p className="pipeline-alert" role="status">
              {stale ? "Leitura com mais de 5 minutos. " : ""}
              {data.partial
                ? data.missing_count > 0
                  ? `${data.missing_count} negócio(s) ausente(s) na última reconciliação. Registros preservados para auditoria. `
                  : "A leitura completa ainda não foi sincronizada. Solicite uma carga em Integração e cargas. "
                : ""}
              {data.connection?.status === "degraded"
                ? "Conexão degradada. Consulte as execuções da integração."
                : ""}
            </p>
          )}
          {!data.connection && (
            <div className="pipeline-empty">
              <h2>Conecte o contrato antes de ler o funil</h2>
              <p>
                Um gestor deve validar o mapeamento e solicitar a primeira carga
                em Integração e cargas.
              </p>
            </div>
          )}
          {data.connection && !items.length && (
            <div className="pipeline-empty">
              <h2>Nenhum negócio sincronizado</h2>
              <p>
                Confira o mapeamento e as execuções da carga. Uma lista vazia
                não significa ausência de receita em risco.
              </p>
            </div>
          )}
          {showIntegration && data.permissions.can_manage && (
            <IntegrationPanel />
          )}
          {data.connection && (
            <>
              <div className="pipeline-board-heading">
                <h2>Trilhas do funil</h2>
                <p>
                  {!data.capabilities.update_stage
                    ? "Provedor sem capacidade de alterar etapas. Somente leitura."
                    : !data.permissions.can_move
                      ? "Somente leitura. Mudanças exigem gestor ou administrador."
                      : "Arraste pelo puxador ou use Mover para. Toda mudança exige confirmação."}
                </p>
              </div>
              <DndContext
                sensors={sensors}
                onDragEnd={dragEnd}
                accessibility={{
                  screenReaderInstructions: {
                    draggable:
                      "Pressione espaço para pegar um negócio, use as setas para mover e espaço para soltar. Escape cancela. Você também pode usar o seletor Mover para no cartão.",
                  },
                }}
              >
                <div
                  className="pipeline-board"
                  role="region"
                  aria-label="Kanban dos negócios do CRM"
                  tabIndex={0}
                >
                  {data.stages.map((stage) => (
                    <StageColumn
                      key={stage.id}
                      id={stage.id}
                      label={stage.label}
                      count={
                        items.filter((deal) => deal.stage === stage.id).length
                      }
                    >
                      {items
                        .filter((deal) => deal.stage === stage.id)
                        .map((deal) => (
                          <DealCard
                            key={deal.id}
                            deal={deal}
                            stages={data.stages}
                            canMove={canMove}
                            onMove={propose}
                          />
                        ))}
                    </StageColumn>
                  ))}
                </div>
              </DndContext>
              {pipeline.hasNextPage && (
                <Button
                  variant="outline"
                  disabled={pipeline.isFetchingNextPage}
                  onClick={() => void pipeline.fetchNextPage()}
                >
                  {pipeline.isFetchingNextPage
                    ? "Carregando…"
                    : "Carregar mais negócios"}
                </Button>
              )}
            </>
          )}
          <footer className="pipeline-footer">
            <ShieldCheckIcon aria-hidden="true" />
            <p>
              Comando humano não é intervenção de IA. Valores deste funil não
              representam receita recuperada ou incremental pelo ARES.
              {data.missing_count > 0
                ? ` ${data.missing_count} negócio(s) ausente(s) preservado(s) para auditoria.`
                : ""}
            </p>
          </footer>
        </>
      )}
      <Dialog.Root
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!open) closeDialog();
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="pipeline-dialog-overlay" />
          <Dialog.Content
            className="pipeline-dialog"
            onPointerDownOutside={(event) => {
              if (move.isPending) event.preventDefault();
            }}
            onEscapeKeyDown={(event) => {
              if (move.isPending) event.preventDefault();
            }}
          >
            <Dialog.Title>Confirmar mudança no CRM</Dialog.Title>
            <Dialog.Description>
              Ação humana com versão esperada e registro de auditoria. O cartão
              só muda após confirmação do provedor.
            </Dialog.Description>
            {intent && (
              <>
                <h3>{intent.deal.title}</h3>
                <p className="pipeline-stage-transition">
                  {data?.stages.find((stage) => stage.id === intent.deal.stage)
                    ?.label ?? intent.deal.stage}{" "}
                  <span>→</span>{" "}
                  {data?.stages.find(
                    (stage) => stage.id === intent.command.stage,
                  )?.label ?? intent.command.stage}
                </p>
                <p>Versão esperada: {intent.command.expected_version}</p>
                <small>
                  Intento <code>{intent.command.idempotency_key}</code>
                </small>
              </>
            )}
            {move.error && (
              <div role="alert" className="pipeline-alert">
                <p>
                  {conflict
                    ? "Conflito de versão ou intento. Recarregue o estado do CRM e revise a mudança antes de criar uma nova intenção."
                    : move.error.message}
                </p>
                {unresolved && (
                  <p>
                    Resultado incerto. Fechar esta janela não cancela uma
                    operação já enviada. A consulta usa a mesma chave, sem criar
                    outra execução.
                  </p>
                )}
                {move.error instanceof PipelineError &&
                  move.error.correlationId && (
                    <code>Correlação: {move.error.correlationId}</code>
                  )}
              </div>
            )}
            <div className="pipeline-actions">
              {conflict ? (
                <Button
                  disabled={pipeline.isFetching}
                  onClick={async () => {
                    const result = await pipeline.refetch();
                    if (!result.isError) {
                      setDialogOpen(false);
                      setIntent(null);
                      move.reset();
                    }
                  }}
                >
                  Recarregar estado e revisar
                </Button>
              ) : (
                <Button
                  disabled={move.isPending || blocked}
                  onClick={() => intent && move.mutate(intent)}
                >
                  {move.isPending
                    ? "Aguardando confirmação…"
                    : unresolved || move.isSuccess
                      ? "Consultar o mesmo intento"
                      : "Confirmar e executar"}
                </Button>
              )}
              <Button
                variant="outline"
                disabled={move.isPending}
                onClick={closeDialog}
              >
                {unresolved ? "Fechar janela" : "Cancelar"}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
