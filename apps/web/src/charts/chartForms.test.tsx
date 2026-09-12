import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChartFrame } from "./ChartFrame";
import { ordinalRamp, shade, tint, type AresThemeTokens } from "./aresTheme";
import { finiteNumber } from "@/lib/numbers";
import type { ChartForm } from "./chartForms";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

function frame(forms: readonly ChartForm[], formKey = "test-chart") {
  return (
    <ChartFrame
      title="Exposição por etapa"
      definition="Onde se concentra o valor"
      unit="BRL"
      period="Recorte atual"
      forms={forms}
      formKey={formKey}
      renderForm={(form) => <div data-testid="plot">forma: {form}</div>}
      table={<table />}
    />
  );
}

describe("chart form selection", () => {
  it("renders the first offered form and switches on demand", async () => {
    const user = userEvent.setup();
    render(frame(["column", "bar", "funnel"]));
    expect(screen.getByTestId("plot")).toHaveTextContent("forma: column");

    await user.click(screen.getByRole("button", { name: /Funil/ }));
    expect(screen.getByTestId("plot")).toHaveTextContent("forma: funnel");
    expect(screen.getByRole("button", { name: /Funil/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("remembers the reader's choice across mounts", async () => {
    const user = userEvent.setup();
    const { unmount } = render(frame(["column", "bar"]));
    await user.click(screen.getByRole("button", { name: /Barras/ }));
    unmount();

    render(frame(["column", "bar"]));
    expect(screen.getByTestId("plot")).toHaveTextContent("forma: bar");
  });

  it("falls back when a remembered form is no longer offered", () => {
    localStorage.setItem("ares-chart-form:test-chart", "funnel");
    render(frame(["column", "bar"]));
    expect(screen.getByTestId("plot")).toHaveTextContent("forma: column");
  });

  it("offers no picker when a single form is honest for the data", () => {
    render(frame(["column"]));
    expect(
      screen.queryByRole("group", { name: /Forma do gráfico/ }),
    ).not.toBeInTheDocument();
  });

  it("survives a browser that refuses storage", async () => {
    const user = userEvent.setup();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    render(frame(["column", "bar"]));
    await user.click(screen.getByRole("button", { name: /Barras/ }));
    expect(screen.getByTestId("plot")).toHaveTextContent("forma: bar");
    vi.restoreAllMocks();
  });
});

describe("colour ramps", () => {
  const tokens = {
    rampLit: 0.51,
    rampShade: 0.44,
  } as AresThemeTokens;

  it("shades darker and tints lighter, unlike zrender lift", () => {
    const luminance = (value: string) => {
      const [r, g, b] = value
        .replace(/rgba?\(|\)/g, "")
        .split(",")
        .map(Number);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    expect(luminance(shade("#e96943", 0.3))).toBeLessThan(
      luminance("rgba(233,105,67,1)"),
    );
    expect(luminance(tint("#e96943", 0.3))).toBeGreaterThan(
      luminance("rgba(233,105,67,1)"),
    );
  });

  it("steps an ordinal ramp monotonically from light to dark", () => {
    const ramp = ordinalRamp("#e96943", 5, tokens);
    const values = ramp.map((value) => {
      const [r, g, b] = value
        .replace(/rgba?\(|\)/g, "")
        .split(",")
        .map(Number);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    });
    for (let index = 1; index < values.length; index += 1)
      expect(values[index]).toBeLessThan(values[index - 1]);
  });
});

describe("numeric coercion at the API boundary", () => {
  // The API serialises Postgres numerics with default=str, so deal_value and
  // score arrive as strings. Number.isFinite on the raw field silently drops
  // every row, which is how the score-against-value matrix shipped empty.
  it("keeps rows whose numerics arrive as strings", () => {
    const rows = [
      { deal_value: "125000.00", score: "0.92" },
      { deal_value: "0.00", score: "0.31" },
      { deal_value: null, score: "0.5" },
    ];
    const points = rows
      .map((row) => {
        const value = finiteNumber(row.deal_value);
        const score = finiteNumber(row.score);
        return value === null || score === null ? null : { value, score };
      })
      .filter(Boolean);

    expect(points).toHaveLength(2);
    expect(points[0]).toEqual({ value: 125000, score: 0.92 });
    expect(rows.filter((row) => Number.isFinite(row.deal_value))).toHaveLength(0);
  });

  it("reads score as a 0..1 fraction, not a percentage", () => {
    expect(finiteNumber("0.92")).toBeLessThanOrEqual(1);
    expect((finiteNumber("0.92") ?? 0) * 100).toBeCloseTo(92);
  });
});
