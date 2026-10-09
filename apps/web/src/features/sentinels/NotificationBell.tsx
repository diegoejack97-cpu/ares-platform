import { useEffect, useRef, useState } from "react";
import { BellIcon, ArrowClockwiseIcon } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";

import { getNotifications, markNotification } from "./api";
import { dateTime } from "@/features/opportunities/format";
import "./notification-bell.css";

export function NotificationBell() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [offset, setOffset] = useState(0);
  const [view, setView] = useState("all");
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: ({
      id,
      revision,
      action,
    }: {
      id: string;
      revision: number;
      action: "read" | "archive" | "unread" | "restore";
    }) => markNotification(id, revision, action),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["sentinel-notifications"] });
    },
    onError: async () => {
      await client.invalidateQueries({ queryKey: ["sentinel-notifications"] });
    },
  });
  const query = useQuery({
    queryKey: ["sentinel-notifications", offset, view],
    queryFn: () => getNotifications(offset, view),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const count = query.data?.unread_count ?? 0;
  return (
    <div className="notification-root" ref={root}>
      <button
        type="button"
        ref={trigger}
        className="notification-trigger"
        aria-label={`Notificações: ${query.isError ? "indisponíveis" : `${count} não lidas`}`}
        aria-expanded={open}
        aria-controls="sentinel-notifications"
        onClick={() => setOpen((value) => !value)}
      >
        <BellIcon size={18} aria-hidden />
        {count > 0 ? (
          <span className="notification-badge" aria-hidden>
            {count}
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
                {count} não lida{count === 1 ? "" : "s"} ·{" "}
                {query.data?.total ?? 0} nesta caixa
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
          <label className="notification-filter">
            Exibir
            <select
              value={view}
              onChange={(e) => {
                setView(e.target.value);
                setOffset(0);
              }}
            >
              <option value="all">Caixa de entrada</option>
              <option value="unread">Não lidas</option>
              <option value="archived">Arquivadas</option>
            </select>
          </label>
          {mutation.isError ? (
            <p role="alert" className="notification-state">
              A notificação mudou ou não pôde ser atualizada. Revise a caixa e
              tente novamente.
            </p>
          ) : null}
          {query.isPending ? (
            <p role="status" className="notification-state">
              Buscando achados…
            </p>
          ) : query.isError ? (
            <p role="alert" className="notification-state">
              Não foi possível consultar os achados.
            </p>
          ) : query.data?.items.length ? (
            <ul>
              {query.data?.items.map((item) => (
                <li key={item.id}>
                  <Link
                    to={`/chat?finding=${encodeURIComponent(item.id)}`}
                    state={{ returnTo: location.pathname }}
                    onClick={() => {
                      setOpen(false);
                    }}
                  >
                    <span className="notification-rule">
                      {item.rule_title ?? "Sentinela"}
                    </span>
                    <strong>{item.title ?? "Oportunidade ARES"}</strong>
                    <small>
                      {
                        {
                          open: "Aberto",
                          updated: "Atualizado",
                          resolved: "Resolvido",
                          superseded: "Superado",
                        }[item.status]
                      }{" "}
                      · {item.is_read ? "Lida" : "Não lida"} ·{" "}
                      {dateTime(item.updated_at)}
                    </small>
                    <span className="notification-summary">
                      {item.interpretation_status === "ready"
                        ? item.interpretation_json?.summary
                        : (item.summary ??
                          "Condição registrada pela sentinela.")}
                    </span>
                    {item.interpretation_status === "pending" ||
                    item.interpretation_status === "running" ? (
                      <small>
                        Resumo por IA pendente; achado já disponível.
                      </small>
                    ) : item.interpretation_status === "degraded" ||
                      item.interpretation_status === "failed" ? (
                      <small>
                        Interpretação indisponível; evidência objetiva
                        preservada.
                      </small>
                    ) : null}
                  </Link>
                  <div className="notification-actions">
                    <button
                      type="button"
                      disabled={mutation.isPending}
                      onClick={() =>
                        mutation.mutate({
                          id: item.id,
                          revision: item.revision,
                          action: item.is_read ? "unread" : "read",
                        })
                      }
                    >
                      {item.is_read ? "Marcar não lida" : "Marcar lida"}
                    </button>
                    <button
                      type="button"
                      disabled={mutation.isPending}
                      onClick={() =>
                        mutation.mutate({
                          id: item.id,
                          revision: item.revision,
                          action: item.is_archived ? "restore" : "archive",
                        })
                      }
                    >
                      {item.is_archived ? "Restaurar" : "Arquivar"}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="notification-state">
              Nenhuma notificação neste filtro.
            </p>
          )}
          <footer>
            <div className="notification-pagination">
              <button
                type="button"
                disabled={offset === 0 || query.isFetching}
                onClick={() => setOffset(Math.max(0, offset - 10))}
              >
                Anteriores
              </button>
              <button
                type="button"
                disabled={query.data?.next_offset == null || query.isFetching}
                onClick={() => setOffset(query.data!.next_offset!)}
              >
                Próximas
              </button>
            </div>
            Fonte: ARES Core · Ler ou arquivar não resolve o risco.
          </footer>
        </section>
      ) : null}
    </div>
  );
}
