import {
  ChartLineUpIcon,
  CirclesFourIcon,
  DatabaseIcon,
  GaugeIcon,
  ShieldCheckIcon,
} from "@phosphor-icons/react";
import { Route, Routes } from "react-router-dom";

import { EventJournalPage } from "@/features/event-journal/event-journal-page";

function App() {
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
          <a className="nav-item active" href="/">
            <DatabaseIcon aria-hidden /> Event Journal
          </a>
          <span className="nav-item future">
            <GaugeIcon aria-hidden /> Command Center <small>M2</small>
          </span>
          <span className="nav-item future">
            <CirclesFourIcon aria-hidden /> Radar ARES <small>M2</small>
          </span>
          <span className="nav-item future">
            <ChartLineUpIcon aria-hidden /> Impacto ARES <small>M6</small>
          </span>
          <span className="nav-item future">
            <ShieldCheckIcon aria-hidden /> Auditoria <small>M3</small>
          </span>
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
          <strong>Tenant demo</strong>
        </div>
        <Routes>
          <Route path="*" element={<EventJournalPage />} />
        </Routes>
      </div>
    </div>
  );
}

export default App;
