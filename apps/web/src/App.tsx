import {
  lazy,
  Suspense,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  ChartLineUpIcon,
  DatabaseIcon,
  FlaskIcon,
  GaugeIcon,
  MoonIcon,
  ListIcon,
  ShieldCheckIcon,
  SidebarSimpleIcon,
  SignOutIcon,
  SunIcon,
  CrosshairIcon,
  KanbanIcon,
} from "@phosphor-icons/react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getOpportunities, getApprovals } from "@/features/opportunities/api";
import { useLiveClock } from "@/lib/live-clock";
import { AresMark } from "@/components/ares-mark";

import { useAuth } from "@/features/auth/auth-context";
import { ApprovalsPage } from "@/features/decisions/approvals-page";
import { EventJournalPage } from "@/features/event-journal/event-journal-page";
import { OpportunityDetailPage } from "@/features/opportunities/opportunity-detail-page";
import { RadarPage } from "@/features/opportunities/radar-page";

const FakeCRMLabPage = lazy(() =>
  import("@/features/fake-crm-lab/fake-crm-lab-page").then((module) => ({
    default: module.FakeCRMLabPage,
  })),
);

const PipelinePage = lazy(() =>
  import("@/features/pipeline/PipelinePage").then((module) => ({ default: module.PipelinePage })),
);

function App() {
  const { session, signOut } = useAuth();
  const sidebarRef = useRef<HTMLElement>(null);
  const [sidebarPinned, setSidebarPinned] = useState(false);
  const [sidebarHovered, setSidebarHovered] = useState(false);
  const [sidebarFocused, setSidebarFocused] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem("ares-theme");
    } catch {
      /* Private browser. */
    }
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  });
  const sidebarExpanded = sidebarPinned || sidebarHovered || sidebarFocused;
  const now = useLiveClock();
  const radar = useQuery({
    queryKey: ["opportunities", "", 0],
    queryFn: () => getOpportunities({}),
    refetchInterval: 15_000,
  });
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: getApprovals,
    refetchInterval: 15_000,
  });
  const overdueCount =
    radar.data?.items.filter(
      (item) => item.sla_at && Date.parse(item.sla_at) <= now,
    ).length ?? 0;

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("ares-theme", theme);
    } catch {
      /* Theme still works in-memory. */
    }
  }, [theme]);

  useEffect(() => {
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!sidebarRef.current?.contains(event.target as Node)) {
        setSidebarPinned(false);
        setSidebarHovered(false);
        setSidebarFocused(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSidebarPinned(false);
      setSidebarHovered(false);
      setSidebarFocused(false);
      if (sidebarRef.current?.contains(document.activeElement))
        (document.activeElement as HTMLElement)?.blur();
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  return (
    <div className="app-shell" data-sidebar-expanded={sidebarExpanded}>
      <aside
        ref={sidebarRef}
        className="sidebar"
        data-expanded={sidebarExpanded}
        onMouseEnter={() => setSidebarHovered(true)}
        onMouseLeave={() => setSidebarHovered(false)}
        onClick={(event) => {
          if (!(event.target as HTMLElement).closest(".sidebar-pin"))
            setSidebarPinned(true);
        }}
        onFocusCapture={() => setSidebarFocused(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget))
            setSidebarFocused(false);
        }}
        aria-label="Menu ARES"
      >
        <div className="brand">
          <span className="brand-mark">
            <AresMark />
          </span>
          <div className="sidebar-copy">
            <strong>ARES</strong>
            <small>PLATFORM</small>
          </div>
          <button
            className="sidebar-pin"
            type="button"
            aria-label={sidebarPinned ? "Menu fixado" : "Fixar menu aberto"}
            aria-pressed={sidebarPinned}
            title={sidebarPinned ? "Clique fora para recolher" : "Fixar menu"}
            onClick={() => {
              setSidebarPinned(!sidebarPinned);
              if (sidebarPinned) {
                setSidebarFocused(false);
                setSidebarHovered(false);
              }
            }}
          >
            <SidebarSimpleIcon
              weight={sidebarPinned ? "fill" : "bold"}
              aria-hidden
            />
          </button>
        </div>
        <div className="product-label sidebar-copy">
          <span>CONNECT</span>
          <span>01</span>
        </div>
        <nav aria-label="Navegação principal">
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/radar"
            title="Radar ARES"
          >
            <CrosshairIcon aria-hidden />
            <span className="nav-copy">Radar ARES</span>
            {overdueCount > 0 ? (
              <small
                className="nav-meta nav-count"
                aria-label={`${overdueCount} SLAs vencidos`}
              >
                {overdueCount}
              </small>
            ) : null}
          </NavLink>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/pipeline"
            title="Funil CRM"
          >
            <KanbanIcon aria-hidden />
            <span className="nav-copy">Funil CRM</span>
          </NavLink>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/approvals"
            title="Aprovações"
          >
            <ShieldCheckIcon aria-hidden />
            <span className="nav-copy">Aprovações</span>
            {approvals.data?.total ? (
              <small className="nav-meta nav-count">
                {approvals.data.total}
              </small>
            ) : null}
          </NavLink>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/journal"
            title="Event Journal"
          >
            <DatabaseIcon aria-hidden />
            <span className="nav-copy">Event Journal</span>
          </NavLink>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/fake-crm"
            title="Laboratório CRM"
          >
            <FlaskIcon aria-hidden />
            <span className="nav-copy">Laboratório CRM</span>
            <small className="nav-meta">TESTE</small>
          </NavLink>
          <span className="nav-item future" title="Command Center">
            <GaugeIcon aria-hidden />
            <span className="nav-copy">Command Center</span>
            <small className="nav-meta">Em breve</small>
          </span>
          <span className="nav-item future" title="Impacto ARES">
            <ChartLineUpIcon aria-hidden />
            <span className="nav-copy">Impacto ARES</span>
            <small className="nav-meta">Em breve</small>
          </span>
        </nav>
        <div className="sidebar-foot">
          <span className="environment-dot" />
          <div className="sidebar-copy">
            <strong>Desenvolvimento</strong>
            <small>FakeCRM · dados locais</small>
          </div>
        </div>
      </aside>
      <div className="app-content">
        <div className="topbar">
          <button
            className="mobile-menu"
            type="button"
            aria-label="Abrir menu"
            aria-expanded={sidebarExpanded}
            onClick={() => setSidebarPinned(true)}
          >
            <ListIcon aria-hidden />
          </button>
          <span className="tenant-name">
            <span className="tenant-monogram">SM</span>Serra Metais
            Distribuidora
          </span>
          <span className="environment-label">AMBIENTE LOCAL</span>
          <span className="topbar-separator" />
          <strong>{session.user.email}</strong>
          <button
            className="theme-toggle"
            type="button"
            onClick={() =>
              setTheme((current) => (current === "dark" ? "light" : "dark"))
            }
            aria-label={`Ativar modo ${theme === "dark" ? "claro" : "escuro"}`}
            title={`Ativar modo ${theme === "dark" ? "claro" : "escuro"}`}
          >
            {theme === "dark" ? (
              <SunIcon aria-hidden />
            ) : (
              <MoonIcon aria-hidden />
            )}
          </button>
          <button
            className="sign-out"
            type="button"
            onClick={() => void signOut()}
          >
            <SignOutIcon aria-hidden /> Sair
          </button>
        </div>
        <Routes>
          <Route path="/" element={<Navigate to="/radar" replace />} />
          <Route path="/journal" element={<EventJournalPage />} />
          <Route path="/pipeline" element={<Suspense fallback={<main className="workspace route-loading" aria-busy="true">Preparando leitura do funil…</main>}><PipelinePage /></Suspense>} />
          <Route
            path="/fake-crm"
            element={
              <Suspense
                fallback={
                  <main className="workspace route-loading">
                    Preparando Laboratório FakeCRM…
                  </main>
                }
              >
                <FakeCRMLabPage />
              </Suspense>
            }
          />
          <Route path="/radar" element={<RadarPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route
            path="/opportunities/:id"
            element={<OpportunityDetailPage />}
          />
          <Route path="*" element={<Navigate to="/radar" replace />} />
        </Routes>
      </div>
    </div>
  );
}

export default App;
