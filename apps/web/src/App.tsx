import {
  ChartLineUpIcon,
  CirclesFourIcon,
  DatabaseIcon,
  GaugeIcon,
  ShieldCheckIcon,
  SignOutIcon,
} from "@phosphor-icons/react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";

import { useAuth } from "@/features/auth/auth-context";
import { ApprovalsPage } from "@/features/decisions/approvals-page";
import { EventJournalPage } from "@/features/event-journal/event-journal-page";
import { OpportunityDetailPage } from "@/features/opportunities/opportunity-detail-page";
import { RadarPage } from "@/features/opportunities/radar-page";

function App() {
  const { session, signOut } = useAuth();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">A</span>
          <div>
            <strong>ARES</strong>
            <small>PLATFORM</small>
          </div>
        </div>
        <div className="product-label">CONNECT · MVP</div>
        <nav aria-label="Navegação principal">
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/journal"
          >
            <DatabaseIcon aria-hidden /> Event Journal
          </NavLink>
          <span className="nav-item future">
            <GaugeIcon aria-hidden /> Command Center <small>M6</small>
          </span>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/radar"
          >
            <CirclesFourIcon aria-hidden /> Radar ARES <small>ATIVO</small>
          </NavLink>
          <span className="nav-item future">
            <ChartLineUpIcon aria-hidden /> Impacto ARES <small>M6</small>
          </span>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/approvals"
          >
            <ShieldCheckIcon aria-hidden /> Aprovações <small>ATIVO</small>
          </NavLink>
        </nav>
        <div className="sidebar-foot">
          <span className="environment-dot" />
          <div>
            <strong>Desenvolvimento</strong>
            <small>FakeCRM · dados locais</small>
          </div>
        </div>
      </aside>
      <div className="app-content">
        <div className="topbar">
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
