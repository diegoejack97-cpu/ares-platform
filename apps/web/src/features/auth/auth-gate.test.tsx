import { StrictMode, useState } from "react";
import type { AuthChangeEvent, Session } from "@supabase/supabase-js";
import { QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AuthGate } from "./auth-gate";
import { useAuth } from "./auth-context";

const auth = vi.hoisted(() => ({
  getSession: vi.fn(),
  getUser: vi.fn(),
  signOut: vi.fn(),
  onAuthStateChange: vi.fn(),
}));
vi.mock("@/lib/supabase", () => ({ supabase: { auth } }));
vi.mock("./login-page", () => ({
  LoginPage: () => <p>Login da empresa</p>,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function session(userId = "user-a", tenantId = "tenant-a", token = "token-a") {
  return {
    access_token: token,
    refresh_token: "synthetic-refresh",
    expires_in: 3600,
    token_type: "bearer",
    user: {
      id: userId,
      aud: "authenticated",
      created_at: "2026-10-02T00:00:00Z",
      app_metadata: { active_tenant_id: tenantId },
      user_metadata: {},
    },
  } satisfies Session;
}

let listener: (event: AuthChangeEvent, next: Session | null) => void;
let initialSession: Session;
let clients: QueryClient[];
let read: (session: Session, signal: AbortSignal) => Promise<string>;

function Product() {
  const { session, signOut } = useAuth();
  const client = useQueryClient();
  const [draft, setDraft] = useState("");
  if (!clients.includes(client)) clients.push(client);
  const result = useQuery({
    // Deliberately identical keys across tenants: the AuthGate must isolate
    // existing screens without relying on every key author remembering scope.
    queryKey: ["private-records"],
    queryFn: ({ signal }) => read(session, signal),
    retry: false,
    staleTime: Infinity,
  });
  return (
    <main>
      <span>{session.user.app_metadata.active_tenant_id}</span>
      <p>{result.isPending ? "Buscando dados" : result.data}</p>
      {result.isError ? <p role="alert">Consulta indisponível</p> : null}
      <input
        aria-label="Mensagem"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button onClick={() => void signOut()}>Sair</button>
    </main>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  initialSession = session();
  clients = [];
  auth.getSession.mockImplementation(async () => ({
    data: { session: initialSession },
  }));
  auth.getUser.mockResolvedValue({
    data: { user: initialSession.user },
    error: null,
  });
  auth.signOut.mockImplementation(async () => {
    listener("SIGNED_OUT", null);
    return { error: null };
  });
  auth.onAuthStateChange.mockImplementation((callback) => {
    listener = callback;
    return { data: { subscription: { unsubscribe: vi.fn() } } };
  });
  read = async (current) =>
    `Registro privado ${current.user.app_metadata.active_tenant_id}`;
});

afterEach(cleanup);

test.each([
  ["outro usuário", () => session("user-b", "tenant-b", "token-b")],
  [
    "outra empresa do mesmo usuário",
    () => session("user-a", "tenant-b", "token-b"),
  ],
])(
  "isolates cache and local state when switching to %s, even if B fails",
  async (_label, next) => {
    const pendingB = deferred<string>();
    read = (current) =>
      current.user.app_metadata.active_tenant_id === "tenant-a"
        ? Promise.resolve("Registro privado empresa A")
        : pendingB.promise;
    render(
      <AuthGate>
        <Product />
      </AuthGate>,
    );
    await screen.findByText("Registro privado empresa A");
    await userEvent.type(
      screen.getByLabelText("Mensagem"),
      "Rascunho privado A",
    );
    const previousClient = clients.at(-1)!;

    await act(async () => listener("SIGNED_IN", next()));
    expect(screen.getByText("tenant-b")).toBeInTheDocument();
    expect(
      screen.queryByText("Registro privado empresa A"),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Mensagem")).toHaveValue("");
    expect(clients.at(-1)).not.toBe(previousClient);
    expect(previousClient.getQueryData(["private-records"])).toBeUndefined();

    await act(async () => pendingB.reject(new Error("Synthetic B offline")));
    await screen.findByRole("alert");
    expect(
      screen.queryByText("Registro privado empresa A"),
    ).not.toBeInTheDocument();
  },
);

test("cancels A and ignores its late response after a direct identity change", async () => {
  const lateA = deferred<string>();
  let signalA: AbortSignal | undefined;
  read = (current, signal) => {
    if (current.user.app_metadata.active_tenant_id === "tenant-a") {
      signalA = signal;
      // Mimic a transport that still resolves after abort.
      return lateA.promise;
    }
    return Promise.resolve("Registro privado empresa B");
  };
  render(
    <AuthGate>
      <Product />
    </AuthGate>,
  );
  await screen.findByText("Buscando dados");
  await waitFor(() => expect(signalA).toBeDefined());
  const previousClient = clients.at(-1)!;
  await act(async () => listener("SIGNED_IN", session("user-b", "tenant-b")));
  await screen.findByText("Registro privado empresa B");
  expect(signalA!.aborted).toBe(true);
  await act(async () => lateA.resolve("Registro tardio privado A"));
  expect(
    screen.queryByText("Registro tardio privado A"),
  ).not.toBeInTheDocument();
  expect(previousClient.getQueryData(["private-records"])).toBeUndefined();
  expect(clients.at(-1)!.getQueryData(["private-records"])).toBe(
    "Registro privado empresa B",
  );
});

test("preserves cache and local state on token refresh of the same identity", async () => {
  render(
    <StrictMode>
      <AuthGate>
        <Product />
      </AuthGate>
    </StrictMode>,
  );
  await screen.findByText("Registro privado tenant-a");
  await userEvent.type(screen.getByLabelText("Mensagem"), "Meu rascunho");
  const currentClient = clients.at(-1)!;
  await act(async () =>
    listener("TOKEN_REFRESHED", session("user-a", "tenant-a", "new-token")),
  );
  expect(clients.at(-1)).toBe(currentClient);
  expect(screen.getByLabelText("Mensagem")).toHaveValue("Meu rascunho");
  expect(screen.getByText("Registro privado tenant-a")).toBeInTheDocument();
});

test("detaches all product state while network logout is still pending", async () => {
  const logout = deferred<{ error: null }>();
  auth.signOut.mockReturnValue(logout.promise);
  render(
    <AuthGate>
      <Product />
    </AuthGate>,
  );
  await screen.findByText("Registro privado tenant-a");
  const previousClient = clients.at(-1)!;
  await userEvent.click(screen.getByRole("button", { name: "Sair" }));
  expect(
    screen.queryByText("Registro privado tenant-a"),
  ).not.toBeInTheDocument();
  expect(previousClient.getQueryData(["private-records"])).toBeUndefined();
  await act(async () => logout.resolve({ error: null }));
  await screen.findByText("Login da empresa");
});

test("an old getUser validation cannot restore A after signing into B", async () => {
  const validationA = deferred<{ error: null }>();
  auth.getUser.mockReturnValue(validationA.promise);
  render(
    <AuthGate>
      <Product />
    </AuthGate>,
  );
  await waitFor(() => expect(auth.getUser).toHaveBeenCalled());
  await act(async () => listener("SIGNED_IN", session("user-b", "tenant-b")));
  await screen.findByText("Registro privado tenant-b");
  await act(async () => validationA.resolve({ error: null }));
  expect(screen.getByText("tenant-b")).toBeInTheDocument();
  expect(screen.queryByText("tenant-a")).not.toBeInTheDocument();
});
