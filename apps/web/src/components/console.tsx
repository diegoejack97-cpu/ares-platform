import type { ReactNode } from "react";
import {
  CheckCircleIcon,
  InfoIcon,
  ProhibitIcon,
  WarningIcon,
} from "@phosphor-icons/react";

export type Tone = "neutral" | "info" | "good" | "warning" | "critical";

const noticeIcons = {
  neutral: InfoIcon,
  info: InfoIcon,
  good: CheckCircleIcon,
  warning: WarningIcon,
  critical: ProhibitIcon,
} as const;

/** A single-line operational notice: tone, marker icon and copy. */
export function NoticeBar({
  tone = "info",
  title,
  children,
  role = "status",
  actions,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
  role?: "status" | "alert";
  actions?: ReactNode;
}) {
  const Icon = noticeIcons[tone];
  return (
    <div className="notice-bar" data-tone={tone} role={role}>
      <Icon aria-hidden weight="fill" />
      <span>
        {title ? <strong>{title}</strong> : null}
        {children}
      </span>
      {actions ? <span className="notice-actions">{actions}</span> : null}
    </div>
  );
}

/** Status badge: colour, marker and a readable label, never colour alone. */
export function StatusBadge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: Tone | "accent";
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className="status-badge" data-tone={tone} title={title}>
      {children}
    </span>
  );
}

/** Capacity meter whose fill colour follows the level: ok, warning, critical. */
export function Meter({
  value,
  max,
  label,
  legend,
  severity = true,
}: {
  value: number;
  max: number;
  label: string;
  legend?: [ReactNode, ReactNode];
  /** Capacity meters colour by severity; similarity meters keep one hue. */
  severity?: boolean;
}) {
  const ratio = max > 0 ? Math.min(value / max, 1) : value > 0 ? 1 : 0;
  const level = !severity
    ? "plain"
    : ratio >= 1
      ? "critical"
      : ratio >= 0.8
        ? "warning"
        : "ok";
  return (
    <div className="meter" data-level={level}>
      <div
        className="meter-track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={Math.min(value, max)}
      >
        <div className="meter-fill" style={{ width: `${ratio * 100}%` }} />
      </div>
      {legend ? (
        <div className="meter-legend">
          <span>{legend[0]}</span>
          <span>{legend[1]}</span>
        </div>
      ) : null}
    </div>
  );
}

/** Label + value tile for a dashboard headline. */
export function StatTile({
  label,
  value,
  note,
  muted,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  muted?: boolean;
}) {
  return (
    <section className="panel stat-tile">
      <span className="stat-label">{label}</span>
      <strong className={`stat-value${muted ? " is-muted" : ""}`}>
        {value}
      </strong>
      {note ? <span className="stat-note">{note}</span> : null}
    </section>
  );
}

/** Provenance for one block: period, source, freshness, attribution. */
export function MetaRow({
  items,
  label,
}: {
  items: Array<[string, ReactNode]>;
  label?: string;
}) {
  return (
    <dl className="meta-row" aria-label={label}>
      {items.map(([term, value]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export const roleLabels: Record<string, string> = {
  admin: "Administrador",
  manager: "Gestor",
  seller: "Vendedor",
  auditor: "Auditor",
};

export function shortId(id: string) {
  return id.slice(0, 8);
}
