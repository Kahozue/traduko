import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invoke(...args),
}));

import { ConnectionProvider, useConnection } from "./connection";

function Probe() {
  const conn = useConnection();
  return <div data-testid="status">{conn.status}</div>;
}

function renderProvider() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <ConnectionProvider>
        <Probe />
      </ConnectionProvider>
    </QueryClientProvider>,
  );
}

test("reaches ready when core is healthy", async () => {
  invoke.mockImplementation(async (command: string) => {
    if (command === "connection_info") {
      return { baseUrl: "http://127.0.0.1:8686", token: "tok", dataRoot: "/tmp/x" };
    }
    return "already_running";
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response('{"status":"ok"}', { status: 200 })),
  );
  vi.stubGlobal(
    "WebSocket",
    class {
      onopen: (() => void) | null = null;
      onmessage: unknown = null;
      onclose: (() => void) | null = null;
      close(): void {}
    },
  );
  renderProvider();
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
});

test("polls tightly while the core is still booting", async () => {
  invoke.mockImplementation(async (command: string) => {
    if (command === "connection_info") {
      return { baseUrl: "http://127.0.0.1:8686", token: "tok", dataRoot: "/tmp/x" };
    }
    return "spawned";
  });
  // Three refusals then a healthy core: at the fast interval that is ~300 ms,
  // well inside the assertion window; at the slow one it would be ~1.5 s.
  let refusals = 3;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async () => {
      if (refusals > 0) {
        refusals -= 1;
        throw new Error("refused");
      }
      return new Response('{"status":"ok"}', { status: 200 });
    }),
  );
  vi.stubGlobal(
    "WebSocket",
    class {
      onopen: (() => void) | null = null;
      onmessage: unknown = null;
      onclose: (() => void) | null = null;
      close(): void {}
    },
  );
  renderProvider();
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"), {
    timeout: 800,
  });
});

test("reports unavailable when core cannot be reached", async () => {
  invoke.mockImplementation(async (command: string) => {
    if (command === "connection_info") {
      return { baseUrl: "http://127.0.0.1:8686", token: null, dataRoot: "/tmp/x" };
    }
    return "unavailable";
  });
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("refused")));
  renderProvider();
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unavailable"));
});
