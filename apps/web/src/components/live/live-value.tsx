import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "@/lib/live-clock";
import { finiteNumber } from "@/lib/numbers";

export function LiveValue({
  value,
  format = defaultFormat,
  worsening = false,
  className = "",
  animateInitial = true,
  empty = "Não informado",
}: {
  value: unknown;
  format?: (value: number) => string;
  worsening?: boolean;
  className?: string;
  animateInitial?: boolean;
  empty?: string;
}) {
  const reduced = useReducedMotion();
  const numeric = finiteNumber(value);
  const previous = useRef(numeric);
  const formatter = useRef(format);
  const first = useRef(true);
  const element = useRef<HTMLSpanElement>(null);
  const [pulse, setPulse] = useState(false);
  useEffect(() => {
    formatter.current = format;
  });
  useEffect(() => {
    let frame = 0;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    if (first.current) {
      first.current = false;
      if (!reduced && animateInitial && numeric !== null) {
        const start = performance.now();
        const target = numeric;
        const tick = (time: number) => {
          const progress = Math.min(1, Math.max(0, (time - start) / 620));
          if (element.current)
            element.current.textContent = formatter.current(
              target * (1 - Math.pow(1 - progress, 3)),
            );
          if (progress < 1) frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
      }
    } else if (previous.current !== numeric && !reduced) {
      setPulse(true);
      timeout = setTimeout(() => setPulse(false), 900);
    }
    previous.current = numeric;
    return () => {
      cancelAnimationFrame(frame);
      if (timeout) clearTimeout(timeout);
    };
  }, [numeric, reduced, animateInitial]);
  return (
    <span
      ref={element}
      className={`live-value ${className}${pulse ? ` delta${worsening ? " worse" : ""}` : ""}`}
      data-value={numeric ?? "missing"}
    >
      {numeric === null ? empty : format(numeric)}
    </span>
  );
}
const defaultFormat = (value: number) =>
  Math.round(value).toLocaleString("pt-BR");
