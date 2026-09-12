import type { Numeric, ScoreBreakdown } from "./types";
import { finiteNumber } from "@/lib/numbers";

export function ScoreBar({
  score,
  breakdown,
}: {
  score: Numeric;
  breakdown: ScoreBreakdown;
}) {
  const numeric = finiteNumber(score);
  const percent =
    numeric === null
      ? null
      : Math.round(Math.min(1, Math.max(0, numeric)) * 100);
  return (
    <div
      className="score-cell"
      title={Object.entries(breakdown)
        .map(([key, part]) => `${key}: ${(part.value * 100).toFixed(0)}`)
        .join(" · ")}
    >
      <strong>{percent ?? "—"}</strong>
      <span
        className="score-track"
        role="img"
        aria-label={
          percent === null ? "Score não informado" : `Score ${percent} de 100`
        }
      >
        <i style={{ width: `${percent ?? 0}%` }} />
      </span>
    </div>
  );
}
