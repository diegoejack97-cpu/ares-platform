import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/live/freshness", () => ({
  Freshness: () => <span>agora</span>,
}));
vi.mock("@/components/live/live-value", () => ({
  LiveValue: ({ value }: { value: number }) => <span>{value}</span>,
}));

import { ChartDataTable, ChartFrame } from "./ChartFrame";

afterEach(cleanup);
const common = {
  title: "Janela de SLA",
  definition: "Prazos de atendimento",
  unit: "Oportunidades",
  period: "Agora",
  source: "ARES Core",
  freshness: 1,
  table: (
    <ChartDataTable
      title="Prazos"
      unit="Oportunidades"
      rows={[{ label: "Vencido", value: 2 }]}
    />
  ),
};

describe("ChartFrame decision context", () => {
  it("keeps the chart mounted when opening its readable table", () => {
    render(
      <ChartFrame {...common}>
        <div role="img" aria-label="Prazos" />
      </ChartFrame>,
    );
    const image = screen.getByRole("img", { name: "Prazos" });
    expect(image.closest(".well")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));
    expect(image).toBeInTheDocument();
    expect(image).not.toBeVisible();
    expect(screen.getByRole("table")).toBeVisible();
    expect(screen.getByText("ARES Core")).toBeVisible();
    expect(screen.getByText("Observação operacional")).toBeVisible();
  });

  it("retains a prior snapshot and gives retry after a failed refresh", () => {
    const retry = vi.fn();
    render(
      <ChartFrame {...common} state="error" onRetry={retry}>
        <div role="img" aria-label="Prazos" />
      </ChartFrame>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "último recorte recebido",
    );
    expect(screen.getByRole("img", { name: "Prazos" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("explains partial values without replacing the known data", () => {
    render(
      <ChartFrame
        {...common}
        state="partial"
        partialMessage="2 registros sem valor; total conhecido pode estar subestimado."
      >
        <div role="img" aria-label="Prazos" />
      </ChartFrame>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "2 registros sem valor",
    );
    expect(screen.getByRole("img", { name: "Prazos" })).toBeVisible();
  });
});
