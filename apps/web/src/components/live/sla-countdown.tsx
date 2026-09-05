import { useEffect, useRef, useState } from "react";
import { useLiveClock } from "@/lib/live-clock";
import { slaLabel } from "@/features/opportunities/format";

export function SlaCountdown({ timestamp }: { timestamp: string | null }) {
  const now = useLiveClock();
  const deadline = timestamp ? Date.parse(timestamp) : NaN;
  const overdue = Number.isFinite(deadline) && now >= deadline;
  const previous = useRef(overdue);
  const [crossed, setCrossed] = useState(false);
  useEffect(() => {
    if (!previous.current && overdue) {
      setCrossed(true);
      window.dispatchEvent(new CustomEvent("ares:sla-overdue", { detail: timestamp }));
    }
    previous.current = overdue;
    const timeout = setTimeout(() => setCrossed(false), 900);
    return () => clearTimeout(timeout);
  }, [overdue, timestamp]);
  return <span className={`sla${overdue ? " overdue" : ""}${crossed ? " delta worse" : ""}`} data-overdue={overdue}>{slaLabel(timestamp, now)}</span>;
}
