import { lazy, Suspense } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowClockwiseIcon,
  CheckCircleIcon,
  DatabaseIcon,
  PlayIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Freshness } from "@/components/live/freshness";
import { LiveValue } from "@/components/live/live-value";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { getJournalEvents, simulateFakeCRMEvent } from "./api";
const EventActivityChart = lazy(() =>
  import("./event-activity-chart").then((module) => ({
    default: module.EventActivityChart,
  })),
);

const formatter = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "medium",
});

export function EventJournalPage() {
  const queryClient = useQueryClient();
  const eventsQuery = useQuery({
    queryKey: ["journal-events"],
    queryFn: getJournalEvents,
    refetchInterval: 10_000,
  });
  const simulateMutation = useMutation({
    mutationFn: simulateFakeCRMEvent,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["journal-events"] }),
  });

  const events = eventsQuery.data?.items ?? [];

  return (
    <main className="workspace journal-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ARES CONNECT / RASTREABILIDADE</span>
          <h1>Event Journal</h1>
          <p>
            Prova da entrada idempotente: webhook FakeCRM, envelope canônico e
            leitura operacional.
          </p>
        </div>
        <Button
          type="button"
          onClick={() => simulateMutation.mutate()}
          disabled={simulateMutation.isPending}
        >
          {simulateMutation.isPending ? (
            <ArrowClockwiseIcon className="animate-spin" aria-hidden />
          ) : (
            <PlayIcon weight="fill" aria-hidden />
          )}
          Simular evento
        </Button>
      </header>

      <section className="status-rail" aria-label="Estado da fatia M1">
        <div>
          <span>Origem</span>
          <strong>{eventsQuery.data?.source ?? "FakeCRM local"}</strong>
        </div>
        <div>
          <span>Eventos persistidos</span>
          <strong className="tabular"><LiveValue value={eventsQuery.data?.total ?? 0} /></strong>
        </div>
        <div>
          <span>Idempotência</span>
          <strong className="status-ok">
            <CheckCircleIcon weight="fill" aria-hidden /> provider_event_id
          </strong>
        </div>
        <div>
          <span>Frescor</span>
          <Freshness timestamp={eventsQuery.dataUpdatedAt} />
        </div>
      </section>

      {simulateMutation.isError && (
        <div className="inline-alert" role="alert">
          <WarningCircleIcon weight="fill" aria-hidden />
          Não foi possível simular o evento. Confirme se a API FastAPI está em
          http://localhost:8000.
        </div>
      )}

      <div className="content-grid">
        <section aria-label="Análise de entrada de eventos">
          {eventsQuery.isLoading ? (
            <Skeleton className="h-[250px] w-full rounded-none" />
          ) : (
            <Suspense
              fallback={<Skeleton className="h-[250px] w-full rounded-none" />}
            >
              <EventActivityChart events={events} freshness={eventsQuery.dataUpdatedAt} state={eventsQuery.isError ? "error" : "ready"} onRetry={() => void eventsQuery.refetch()} />
            </Suspense>
          )}
        </section>

        <aside
          className="panel contract-panel"
          aria-labelledby="contract-title"
        >
          <div className="panel-heading">
            <div>
              <h2 id="contract-title">Contrato executável</h2>
              <p>O que esta fatia já prova</p>
            </div>
            <DatabaseIcon size={22} aria-hidden />
          </div>
          <ol className="chain-list">
            <li>
              <span>01</span> assinatura HMAC verificada
            </li>
            <li>
              <span>02</span> evento normalizado
            </li>
            <li>
              <span>03</span> deduplicação por evento externo
            </li>
            <li>
              <span>04</span> correlation_id preservado
            </li>
            <li>
              <span>05</span> leitura disponível à interface
            </li>
          </ol>
          <p className="contract-note">
            Persistência PostgreSQL ativa. Auth/RLS e isolamento por tenant são
            verificados pelos testes da migration M1.
          </p>
        </aside>
      </div>

      <section className="panel table-panel" aria-labelledby="events-title">
        <div className="panel-heading">
          <div>
            <h2 id="events-title">Eventos registrados</h2>
            <p>Alternativa tabular acessível à visualização</p>
          </div>
          {eventsQuery.isFetching && !eventsQuery.isLoading && (
            <span className="refreshing">
              <ArrowClockwiseIcon className="animate-spin" aria-hidden />{" "}
              atualizando
            </span>
          )}
        </div>

        {eventsQuery.isLoading ? (
          <div className="table-loading" aria-label="Carregando eventos">
            <Skeleton className="h-10 w-full rounded-none" />
            <Skeleton className="h-10 w-full rounded-none" />
            <Skeleton className="h-10 w-full rounded-none" />
          </div>
        ) : eventsQuery.isError && !eventsQuery.data ? (
          <div className="empty-state" role="alert">
            <WarningCircleIcon size={28} weight="fill" aria-hidden />
            <strong>API indisponível</strong>
            <span>
              Inicie o FastAPI e tente novamente. Nenhum dado fictício foi
              exibido.
            </span>
            <Button variant="outline" onClick={() => eventsQuery.refetch()}>
              Tentar novamente
            </Button>
          </div>
        ) : events.length === 0 ? (
          <div className="empty-state">
            <DatabaseIcon size={28} aria-hidden />
            <strong>Journal vazio</strong>
            <span>Simule um evento para percorrer a primeira fatia da M1.</span>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Registrado em</TableHead>
                <TableHead>Evento</TableHead>
                <TableHead>Agregado</TableHead>
                <TableHead>Origem</TableHead>
                <TableHead>Correlação</TableHead>
                <TableHead>Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event) => (
                <TableRow key={event.id}>
                  <TableCell className="tabular">
                    {formatter.format(new Date(event.recorded_at))}
                  </TableCell>
                  <TableCell className="event-type">
                    {event.event_type}
                  </TableCell>
                  <TableCell>{event.aggregate_id}</TableCell>
                  <TableCell>{event.producer}</TableCell>
                  <TableCell>
                    <code title={event.correlation_id}>
                      {event.correlation_id.slice(0, 8)}
                    </code>
                  </TableCell>
                  <TableCell>
                    <Badge className="recorded-badge" variant="outline">
                      registrado
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </main>
  );
}
