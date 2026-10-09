import { useLiveClock } from "@/lib/live-clock";

/** Presentation freshness threshold, not a commercial SLA or backend policy. */
export const STALE_AFTER_MS = 90_000;
export function Freshness({
  timestamp,
  staleAfterMs = STALE_AFTER_MS,
}: {
  timestamp: number | string | null | undefined;
  staleAfterMs?: number;
}) {
  const now = useLiveClock();
  const stamp =
    typeof timestamp === "string" ? Date.parse(timestamp) : timestamp;
  const valid =
    typeof stamp === "number" && Number.isFinite(stamp) && stamp > 0;
  const age = valid ? Math.max(0, now - stamp) : 0;
  const seconds = Math.floor(age / 1_000);
  const text = !valid
    ? "aguardando dados"
    : seconds < 5
      ? "agora"
      : seconds < 60
        ? `há ${seconds} s`
        : `há ${Math.floor(seconds / 60)} min`;
  return (
    <span
      className={`freshness-chip${age > staleAfterMs ? " is-stale" : ""}`}
      title={
        valid
          ? `Última leitura bem-sucedida: ${new Date(stamp).toLocaleString("pt-BR")}`
          : "Nenhuma leitura concluída"
      }
    >
      <i aria-hidden />
      {age > staleAfterMs ? "Leitura atrasada · " : "Atualizado "}
      {text}
    </span>
  );
}
