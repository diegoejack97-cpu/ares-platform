import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const chart = vi.hoisted(() => ({
  setOption: vi.fn(),
  setTheme: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
  isDisposed: vi.fn(() => false),
}));
const init = vi.hoisted(() => vi.fn(() => chart));
vi.mock("echarts/core", () => ({
  init,
  use: vi.fn(),
  registerTheme: vi.fn(),
  color: {},
  graphic: {},
}));
vi.mock("echarts/charts", () => ({
  BarChart: {},
  LineChart: {},
  PieChart: {},
  FunnelChart: {},
  TreemapChart: {},
}));
vi.mock("echarts/components", () => ({
  GraphicComponent: {},
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  MarkLineComponent: {},
}));
vi.mock("echarts/renderers", () => ({ SVGRenderer: {} }));

import { AresChart } from "./AresChart";

describe("AresChart snapshot lifecycle", () => {
  let reduced = false;
  let motionListener: (() => void) | undefined;

  beforeEach(() => {
    vi.clearAllMocks();
    reduced = false;
    document.documentElement.dataset.theme = "light";
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => ({
        get matches() {
          return reduced;
        },
        addEventListener: (_event: string, listener: () => void) => {
          motionListener = listener;
        },
        removeEventListener: () => {
          motionListener = undefined;
        },
      })),
    });
  });
  afterEach(cleanup);

  it("merges changed values without replacing the chart instance", () => {
    const first = { series: [{ id: "count", type: "bar", data: [3] }] };
    const next = { series: [{ id: "count", type: "bar", data: [7] }] };
    const { rerender, unmount } = render(
      <AresChart option={first} label="Contagem" />,
    );
    expect(chart.setOption).toHaveBeenCalledTimes(1);
    rerender(<AresChart option={next} label="Contagem" />);
    expect(init).toHaveBeenCalledTimes(1);
    expect(chart.setOption).toHaveBeenLastCalledWith(
      expect.objectContaining({ series: next.series }),
      expect.objectContaining({ notMerge: false }),
    );
    expect(chart.dispose).not.toHaveBeenCalled();
    unmount();
    expect(chart.dispose).toHaveBeenCalledTimes(1);
  });

  it("does not repaint when an unrelated parent clock ticks", () => {
    const option = { series: [{ id: "count", type: "bar", data: [3] }] };
    const { rerender } = render(<AresChart option={option} label="Contagem" />);
    rerender(<AresChart option={option} label="Contagem" />);
    expect(chart.setOption).toHaveBeenCalledTimes(1);
    expect(init).toHaveBeenCalledTimes(1);
  });

  it("applies a new theme to the existing renderer", () => {
    const { rerender } = render(
      <AresChart option={{ series: [] }} label="Contagem" />,
    );
    document.documentElement.dataset.theme = "dark";
    rerender(<AresChart option={{ series: [] }} label="Contagem" />);
    expect(chart.setTheme).toHaveBeenCalledWith("ares", { silent: true });
    expect(init).toHaveBeenCalledTimes(1);
  });

  it("responds immediately to reduced motion while retaining the values", () => {
    const option = { series: [{ id: "count", type: "bar", data: [7] }] };
    render(<AresChart option={option} label="Contagem" />);
    act(() => {
      reduced = true;
      motionListener?.();
    });
    expect(chart.setOption).toHaveBeenLastCalledWith(
      expect.objectContaining({ animation: false, series: option.series }),
      expect.objectContaining({ notMerge: false }),
    );
  });
});
