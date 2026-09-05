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
  CirclesFourIcon,
  DatabaseIcon,
  FlaskIcon,
  GaugeIcon,
  MoonIcon,
  ShieldCheckIcon,
  SidebarSimpleIcon,
  SignOutIcon,
  SunIcon,
} from "@phosphor-icons/react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";

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

function App() {
  const { session, signOut } = useAuth();
  const sidebarRef = useRef<HTMLElement>(null);
  const [sidebarPinned, setSidebarPinned] = useState(false);
  const [sidebarHovered, setSidebarHovered] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const stored = localStorage.getItem("ares-theme");
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  });
  const sidebarExpanded = sidebarPinned || sidebarHovered;

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("ares-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!sidebarPinned) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!sidebarRef.current?.contains(event.target as Node)) {
        setSidebarPinned(false);
      }
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () =>
      document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, [sidebarPinned]);

  return (
    <div className="app-shell" data-sidebar-expanded={sidebarExpanded}>
      <aside
        ref={sidebarRef}
        className="sidebar"
        data-expanded={sidebarExpanded}
        onMouseEnter={() => setSidebarHovered(true)}
        onMouseLeave={() => setSidebarHovered(false)}
        onClickCapture={() => setSidebarPinned(true)}
      >
        <div className="brand">
          <span className="brand-mark">A</span>
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
          >
            <SidebarSimpleIcon
              weight={sidebarPinned ? "fill" : "regular"}
              aria-hidden
            />
          </button>
        </div>
        <div className="product-label sidebar-copy">CONNECT · MVP</div>
        <nav aria-label="Navegação principal">
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
            <small className="nav-meta">M4</small>
          </NavLink>
          <span className="nav-item future" title="Command Center">
            <GaugeIcon aria-hidden />
            <span className="nav-copy">Command Center</span>
            <small className="nav-meta">M6</small>
          </span>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/radar"
            title="Radar ARES"
          >
            <CirclesFourIcon aria-hidden />
            <span className="nav-copy">Radar ARES</span>
            <small className="nav-meta">ATIVO</small>
          </NavLink>
          <span className="nav-item future" title="Impacto ARES">
            <ChartLineUpIcon aria-hidden />
            <span className="nav-copy">Impacto ARES</span>
            <small className="nav-meta">M6</small>
          </span>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/approvals"
            title="Aprovações"
          >
            <ShieldCheckIcon aria-hidden />
            <span className="nav-copy">Aprovações</span>
            <small className="nav-meta">ATIVO</small>
          </NavLink>
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
          <span>Serra Metais Distribuidora</span>
          <span className="topbar-separator" />
          <strong>{session.user.email}</strong>
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
