import { useCallback, useState } from "react";

/**
 * The forms a chart may take. A frame offers only the ones that stay honest for
 * its data, so switching form can never turn a reading into a wrong claim.
 */
export type ChartForm =
  | "column"
  | "bar"
  | "line"
  | "area"
  | "scatter"
  | "heatmap"
  | "funnel"
  | "donut"
  | "treemap";

export interface ChartFormSpec {
  id: ChartForm;
  label: string;
  /** Why a reader would pick it — shown as the control's title. */
  hint: string;
}

export const CHART_FORMS: Record<ChartForm, ChartFormSpec> = {
  column: {
    id: "column",
    label: "Colunas",
    hint: "Compara magnitude entre categorias, na ordem do funil",
  },
  bar: {
    id: "bar",
    label: "Barras",
    hint: "Compara magnitude com rótulos longos, sem truncar",
  },
  line: {
    id: "line",
    label: "Linha",
    hint: "Mostra a evolução ao longo do tempo",
  },
  area: {
    id: "area",
    label: "Área",
    hint: "Evolução de uma série única, com volume acumulado",
  },
  scatter: {
    id: "scatter",
    label: "Dispersão",
    hint: "Relaciona duas medidas e revela concentração",
  },
  heatmap: {
    id: "heatmap",
    label: "Mapa de calor",
    hint: "Concentração em uma grade de duas dimensões",
  },
  funnel: {
    id: "funnel",
    label: "Funil",
    hint: "Perda entre etapas sucessivas",
  },
  donut: {
    id: "donut",
    label: "Rosca",
    hint: "Parte do todo, à primeira vista — não para comparar valores próximos",
  },
  treemap: {
    id: "treemap",
    label: "Blocos",
    hint: "Parte do todo quando há muitas categorias",
  },
};

const STORAGE_PREFIX = "ares-chart-form:";

function readStored(key: string, allowed: readonly ChartForm[]) {
  try {
    const stored = localStorage.getItem(STORAGE_PREFIX + key);
    if (stored && allowed.includes(stored as ChartForm))
      return stored as ChartForm;
  } catch {
    /* Private browser: the default form still works. */
  }
  return null;
}

/**
 * Remembers the reader's chosen form per chart. Falls back to the frame's first
 * offered form whenever the stored one is no longer on offer.
 */
export function useChartForm(key: string, forms: readonly ChartForm[]) {
  const fallback = forms[0];
  const [chosen, setChosen] = useState<ChartForm | null>(() =>
    readStored(key, forms),
  );
  // Derived, not synchronised: a form that is no longer offered simply falls back.
  const form = chosen && forms.includes(chosen) ? chosen : fallback;

  const choose = useCallback(
    (next: ChartForm) => {
      setChosen(next);
      try {
        localStorage.setItem(STORAGE_PREFIX + key, next);
      } catch {
        /* The choice still applies for this session. */
      }
    },
    [key],
  );

  return [form, choose] as const;
}
