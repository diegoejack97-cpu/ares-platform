import type { ScoreBreakdown } from "./types";

export function ScoreBar({
  score,
  breakdown,
}: {
  score: number;
  breakdown: ScoreBreakdown;
}) {
  return (
    <div
      className="score-cell"
      title={Object.entries(breakdown)
        .map(([key, part]) => `${key}: ${(part.value * 100).toFixed(0)}`)
        .join(" · ")}
    >
      <strong>{Math.round(score * 100)}</strong>
      <span
        className="score-track"
        aria-label={`Score ${Math.round(score * 100)} de 100`}
      >
        <i style={{ width: `${score * 100}%` }} />
      </span>
    </div>
  );
}
