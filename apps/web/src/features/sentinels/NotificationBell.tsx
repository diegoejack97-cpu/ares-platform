import { useEffect, useRef, useState } from "react";
import { BellIcon, ArrowClockwiseIcon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { getSentinels } from "@/features/opportunities/api";
import { dateTime } from "@/features/opportunities/format";
import "./notification-bell.css";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const query = useQuery({
    queryKey: ["sentinel-findings"],
    queryFn: getSentinels,
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const count = query.data?.items.length ?? 0;
  return (
    <div className="notification-root" ref={root}>
      <button
        type="button"
        className="notification-trigger"
        aria-label={`Notificações: ${count}${query.data?.truncated ? " ou mais" : ""} achados atuais`}
        aria-expanded={open}
        aria-controls="sentinel-notifications"
        onClick={() => setOpen((value) => !value)}
      >
        <BellIcon size={18} aria-hidden />
        {count > 0 ? (
          <span className="notification-badge" aria-hidden>
            {count}
            {query.data?.truncated ? "+" : ""}
          </span>
        ) : null}
      </button>
      {open ? (
        <section
          id="sentinel-notifications"
          className="notification-panel"
          aria-label="Notificações das sentinelas"
        >
          <header>
            <div>
              <strong>Notificações</strong>
              <span>
                {count} achado{count === 1 ? "" : "s"} atual
                {count === 1 ? "" : "is"}
              </span>
            </div>
            <button
              type="button"
              aria-label="Atualizar notificações"
              disabled={query.isFetching}
              onClick={() => void query.refetch()}
            >
              <ArrowClockwiseIcon size={16} aria-hidden />
            </button>
          </header>
          {query.isPending ? (
            <p role="status" className="notification-state">
              Buscando achados…
            </p>
          ) : query.isError ? (
            <p role="alert" className="notification-state">
              Não foi possível consultar os achados.
            </p>
          ) : count ? (
            <ul>
              {query.data?.items.map((item) => (
                <li key={item.id}>
                  <Link
                    to={`/opportunities/${item.opportunity_id}`}
                    onClick={() => setOpen(false)}
                  >
                    <span className="notification-rule">
                      {item.rule_title ?? "Sentinela"}
                    </span>
                    <strong>{item.title ?? "Oportunidade ARES"}</strong>
                    <small>Detectado em {dateTime(item.detected_at)}</small>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="notification-state">
              {query.data?.checked_at
                ? "Nenhum achado atual."
                : "Aguardando a primeira verificação."}
            </p>
          )}
          <footer>
            Fonte: ARES Core · Verificado em{" "}
            {dateTime(query.data?.checked_at ?? null)}
            {query.data?.truncated ? " · Primeiros 25 achados" : ""}
          </footer>
        </section>
      ) : null}
    </div>
  );
}
