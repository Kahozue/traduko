import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import { useQueryClient } from "@tanstack/react-query";
import { ApiClient } from "./api/client";
import { EventStream } from "./events/stream";
import { assistantLive, eventLog } from "./events/store";

interface ConnectionInfo {
  baseUrl: string;
  token: string | null;
  dataRoot: string;
}

export type ConnectionState =
  | { status: "connecting"; dataRoot: string | null; baseUrl: string | null }
  | { status: "unavailable"; dataRoot: string; baseUrl: string }
  | { status: "ready"; dataRoot: string; baseUrl: string; api: ApiClient };

type ConnectionValue = ConnectionState & { retry: () => void };

export const ConnectionContext = createContext<ConnectionValue | null>(null);

// The bundled core answers /health under a second, so the first seconds are
// polled tightly to avoid sitting on a ready core. The slow tail covers the
// first run after an install, where macOS still has to validate every
// freshly installed binary and the core takes several seconds. The app
// spawns and owns that process, so it waits generously rather than telling
// the user to start the core by hand.
const HEALTH_FAST_INTERVAL_MS = 100;
const HEALTH_FAST_WINDOW_MS = 3000;
const HEALTH_SLOW_INTERVAL_MS = 500;
const HEALTH_TIMEOUT_MS = 60000;

async function healthOk(baseUrl: string): Promise<boolean> {
  try {
    const response = await fetch(`${baseUrl}/health`);
    return response.ok;
  } catch {
    return false;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ConnectionState>({
    status: "connecting",
    dataRoot: null,
    baseUrl: null,
  });
  const streamRef = useRef<EventStream | null>(null);
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    let disposed = false;

    async function connect(): Promise<void> {
      setState({ status: "connecting", dataRoot: null, baseUrl: null });
      const info = await invoke<ConnectionInfo>("connection_info");
      const outcome = await invoke<string>("ensure_core_running");
      let healthy = false;
      const startedAt = Date.now();
      while (!disposed && Date.now() - startedAt < HEALTH_TIMEOUT_MS) {
        if (await healthOk(info.baseUrl)) {
          healthy = true;
          break;
        }
        if (outcome === "unavailable") break;
        const fast = Date.now() - startedAt < HEALTH_FAST_WINDOW_MS;
        await sleep(fast ? HEALTH_FAST_INTERVAL_MS : HEALTH_SLOW_INTERVAL_MS);
      }
      if (disposed) return;
      const fresh = await invoke<ConnectionInfo>("connection_info");
      if (!healthy || !fresh.token) {
        setState({ status: "unavailable", dataRoot: fresh.dataRoot, baseUrl: fresh.baseUrl });
        return;
      }
      const api = new ApiClient(fresh.baseUrl, fresh.token);
      const stream = new EventStream(api.wsUrl(), {
        onEvent: (event) => {
          // Assistant live-progress events feed the panel's own store; they
          // are not task events and must not churn the task query cache.
          if (event.type.startsWith("assistant_")) {
            assistantLive.push(event);
            return;
          }
          eventLog.push(event);
          if (event.type === "stage_progress" || event.type === "agent_round") return;
          queryClient.invalidateQueries({ queryKey: ["tasks"] });
          queryClient.invalidateQueries({ queryKey: ["task", event.project, event.task_id] });
          if (event.type.startsWith("budget")) {
            queryClient.invalidateQueries({ queryKey: ["budget"] });
          }
        },
      });
      stream.start();
      streamRef.current = stream;
      setState({ status: "ready", dataRoot: fresh.dataRoot, baseUrl: fresh.baseUrl, api });
    }

    void connect();
    return () => {
      disposed = true;
      streamRef.current?.stop();
      streamRef.current = null;
    };
  }, [attempt, queryClient]);

  return (
    <ConnectionContext.Provider value={{ ...state, retry }}>
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection(): ConnectionValue {
  const value = useContext(ConnectionContext);
  if (value === null) throw new Error("useConnection outside ConnectionProvider");
  return value;
}

export function useApi(): ApiClient {
  const conn = useConnection();
  if (conn.status !== "ready") throw new Error("api not ready");
  return conn.api;
}
