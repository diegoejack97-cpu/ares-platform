import { expect, test } from "vitest";
import { readThemeTokens } from "./aresTheme";
import { stackedOption } from "./analysisOptions";

const tokens = readThemeTokens();
const spec = {
  categories: ["01/09", "02/09", "03/09"],
  series: [
    { key: "a", label: "A (sev. 5)", color: "#e96943", values: [1, null, 3] },
    { key: "b", label: "B (sev. 3)", color: "#7089a6", values: [0, 2, 0] },
  ],
  measure: "sinais",
  format: (value: number) => `${value}`,
  stack: "signals",
};

test("stacked bars share one baseline, keep square joins and null gaps", () => {
  const option = stackedOption("column", spec, tokens) as {
    series: Array<{
      id: string;
      stack: string;
      data: Array<number | null>;
      itemStyle: { borderRadius: number };
    }>;
    legend: { data: string[] };
    xAxis: { type: string };
    yAxis: { type: string };
  };
  expect(option.series.map((entry) => entry.id)).toEqual(["a", "b"]);
  expect(option.series.every((entry) => entry.stack === "signals")).toBe(true);
  expect(
    option.series.every((entry) => entry.itemStyle.borderRadius === 0),
  ).toBe(true);
  expect(option.series[0].data[1]).toBeNull();
  expect(option.legend.data).toEqual(["A (sev. 5)", "B (sev. 3)"]);
  expect(option.xAxis.type).toBe("category");
  expect(option.yAxis.type).toBe("value");
});

test("the bar form swaps the axes without touching the series", () => {
  const option = stackedOption("bar", spec, tokens) as {
    xAxis: { type: string };
    yAxis: { type: string };
  };
  expect(option.xAxis.type).toBe("value");
  expect(option.yAxis.type).toBe("category");
});
