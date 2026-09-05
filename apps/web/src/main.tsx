import { StrictMode } from "react";
import { IconContext } from "@phosphor-icons/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthGate } from "@/features/auth/auth-gate";
import "./index.css";
import App from "./App.tsx";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

// Initialize the theme before the authentication surface renders.
let initialTheme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
try { const saved = localStorage.getItem("ares-theme"); if(saved === "dark" || saved === "light") initialTheme = saved; } catch { /* In-memory theme is available. */ }
document.documentElement.dataset.theme = initialTheme;
document.documentElement.classList.toggle("dark", initialTheme === "dark");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <IconContext.Provider value={{ weight: "bold", className: "icon-emboss" }}>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <TooltipProvider>
          <AuthGate>
            <App />
          </AuthGate>
        </TooltipProvider>
      </BrowserRouter>
    </QueryClientProvider>
    </IconContext.Provider>
  </StrictMode>,
);
