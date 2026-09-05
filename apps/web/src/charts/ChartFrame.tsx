import { useId, useState, type CSSProperties, type ReactNode } from "react";
import {
  ChartBarIcon,
  TableIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

import { Freshness } from "@/components/live/freshness";
import { LiveValue } from "@/components/live/live-value";

import "./charts.css";

export type ChartState =
  "ready" | "loading" | "empty" | "partial" | "stale" | "error";
export interface ChartMetadata {
  freshness?: number | string | null;
  source?: string;
  state?: ChartState;
  onRetry?: () => void;
  partialMessage?: string;
}

export function ChartFrame({
  title,
  definition,
  unit,
  period,
  source = "ARES Core / FakeCRM",
  freshness,
  attribution = "Observação operacional",
  state = "ready",
  table,
  children,
  onRetry,
  partialMessage,
  hasData = true,
  emptyMessage = "Ainda não há registros neste recorte.",
  className = "",
  actions,
}: ChartMetadata & {
  title: string;
  definition: string;
  unit: string;
  period: string;
  attribution?: string;
  table: ReactNode;
  children: ReactNode;
  hasData?: boolean;
  emptyMessage?: string;
  className?: string;
  actions?: ReactNode;
}) {
  const id = useId();
  const [view, setView] = useState<"chart" | "table">("chart");
  const blank = !hasData || state === "empty";
  const stateMessage =
    state === "error"
      ? hasData
        ? "A atualização falhou. Exibindo o último recorte recebido."
        : "Não foi possível carregar esta análise."
      : state === "stale"
        ? "Recorte desatualizado. Os valores permanecem disponíveis para consulta."
        : state === "partial"
          ? (partialMessage ??
            "Recorte parcial. Alguns registros não puderam ser incluídos.")
          : null;

  return (
    <section
      className={`chart-frame s1 sheen ${className}`}
      aria-labelledby={`${id}-title`}
      data-chart-frame
      data-state={state}
    >
      <header className="chart-frame-header">
        <div className="chart-frame-heading">
          <h2 id={`${id}-title`}>{title}</h2>
          <p>{definition}</p>
        </div>
        <div
          className="chart-view-toggle well"
          role="group"
          aria-label={`Visualização de ${title}`}
        >
          <button
            type="button"
            className="press"
            aria-pressed={view === "chart"}
            aria-controls={`${id}-chart`}
            onClick={() => setView("chart")}
          >
            <ChartBarIcon weight="bold" aria-hidden />
            Gráfico
          </button>
          <button
            type="button"
            className="press"
            aria-pressed={view === "table"}
            aria-controls={`${id}-table`}
            onClick={() => setView("table")}
          >
            <TableIcon weight="bold" aria-hidden />
            Tabela
          </button>
        </div>
      </header>
      <div className="chart-frame-context">
        <span>{unit}</span>
        <span>{period}</span>
        {actions}
      </div>
      {stateMessage && (
        <div
          className={`chart-state-notice chart-state-${state}`}
          role={state === "error" ? "alert" : "status"}
        >
          <WarningCircleIcon weight="bold" aria-hidden />
          <span>{stateMessage}</span>
          {onRetry && (state === "error" || state === "stale") && (
            <button type="button" className="s2 press" onClick={onRetry}>
              Tentar novamente
            </button>
          )}
        </div>
      )}
      <div className="chart-frame-body">
        {state === "loading" && blank ? (
          <div
            className="chart-plot chart-state-loading well"
            role="status"
            aria-label={`Carregando ${title}`}
          >
            <div className="chart-skeleton-bars" aria-hidden>
              <i />
              <i />
              <i />
              <i />
              <i />
            </div>
            <span>Preparando a leitura dos dados…</span>
          </div>
        ) : blank ? (
          <div className="chart-plot chart-state-empty well" role="status">
            <ChartBarIcon size={26} weight="duotone" aria-hidden />
            <strong>
              {state === "error"
                ? "Análise indisponível"
                : "Sem dados para esta análise"}
            </strong>
            <span>{emptyMessage}</span>
            {onRetry && state !== "error" && (
              <button type="button" className="s2 press" onClick={onRetry}>
                Atualizar recorte
              </button>
            )}
          </div>
        ) : (
          <>
            <div
              className="chart-plot well"
              id={`${id}-chart`}
              hidden={view !== "chart"}
            >
              {children}
            </div>
            <div
              className="chart-table-well well"
              id={`${id}-table`}
              hidden={view !== "table"}
            >
              {table}
            </div>
          </>
        )}
      </div>
      <footer className="chart-frame-footer">
        <span className="chart-source">
          <span>Fonte</span> {source}
        </span>
        <span className="chart-freshness">
          <span>Frescor</span> <Freshness timestamp={freshness} />
        </span>
        <span className="chart-attribution">
          <span>Atribuição</span> {attribution}
        </span>
      </footer>
    </section>
  );
}

export interface ChartDatum {
  label: string;
  value: number | null;
  color?: string;
  detail?: string;
  worsening?: boolean;
}

export function ChartDataTable({
  title,
  rows,
  unit,
  format = String,
}: {
  title: string;
  rows: ChartDatum[];
  unit: string;
  format?: (value: number) => string;
}) {
  return (
    <table className="chart-data-table">
      <caption className="sr-only">{title}</caption>
      <thead>
        <tr>
          <th scope="col">Categoria</th>
          <th scope="col">{unit}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label}>
            <th scope="row">
              {row.label}
              {row.detail && <small>{row.detail}</small>}
            </th>
            <td>
              {row.value === null ? (
                "Não informado"
              ) : (
                <LiveValue
                  value={row.value}
                  format={format}
                  worsening={row.worsening}
                />
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ChartLegend({
  rows,
  format = String,
  compact = false,
}: {
  rows: ChartDatum[];
  format?: (value: number) => string;
  compact?: boolean;
}) {
  return (
    <ul
      className={`chart-legend ${compact ? "chart-legend-compact" : ""}`}
      aria-label="Valores do gráfico"
    >
      {rows.map((row) => (
        <li key={row.label}>
          <span
            className="chart-legend-key"
            style={
              { "--legend-color": row.color ?? "var(--aco)" } as CSSProperties
            }
            aria-hidden
          />
          <span className="chart-legend-label">{row.label}</span>
          <strong>
            {row.value === null ? (
              "Não informado"
            ) : (
              <LiveValue
                value={row.value}
                format={format}
                worsening={row.worsening}
              />
            )}
          </strong>
        </li>
      ))}
    </ul>
  );
}
