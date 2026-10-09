import { lazy, StrictMode, Suspense } from "react";
import { IconContext } from "@phosphor-icons/react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthGate } from "@/features/auth/auth-gate";
import "./index.css";
import App from "./App.tsx";
const ProviderPage = lazy(() =>
  import("./features/provider/ProviderPage").then((module) => ({
    default: module.ProviderPage,
  })),
);

// Initialize the theme before the authentication surface renders.
let initialTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
  ? "dark"
  : "light";
try {
  const saved = localStorage.getItem("ares-theme");
  if (saved === "dark" || saved === "light") initialTheme = saved;
} catch {
  /* In-memory theme is available. */
}
document.documentElement.dataset.theme = initialTheme;
document.documentElement.classList.toggle("dark", initialTheme === "dark");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <IconContext.Provider value={{ weight: "bold", className: "icon-emboss" }}>
      <BrowserRouter>
        <TooltipProvider>
          <Routes>
            <Route
              path="/central-admin/*"
              element={
                <Suspense
                  fallback={<p role="status">Carregando painel do provedor…</p>}
                >
                  <ProviderPage />
                </Suspense>
              }
            />
            <Route
              path="/admin/*"
              element={<Navigate to="/central-admin" replace />}
            />
            <Route
              path="/*"
              element={
                <AuthGate>
                  <App />
                </AuthGate>
              }
            />
          </Routes>
        </TooltipProvider>
      </BrowserRouter>
    </IconContext.Provider>
  </StrictMode>,
);
