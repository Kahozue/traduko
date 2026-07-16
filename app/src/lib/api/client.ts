import type {
  BudgetInfo,
  PreflightReport,
  TaskIndexRow,
  TaskRecord,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(`api error ${status}`);
  }
}

export interface TaskCreateBody {
  input_path: string;
  profile: string;
  project?: string;
}

export class ApiClient {
  constructor(
    private baseUrl: string,
    private token: string,
    // Bound to globalThis: WebKit's fetch throws "Illegal invocation" when
    // called with any other receiver, and this.fetchFn(...) would do that.
    private fetchFn: typeof fetch = fetch.bind(globalThis),
  ) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchFn(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(response.status, (body as { detail?: unknown })?.detail ?? body);
    }
    return body as T;
  }

  health(): Promise<{ status: string }> {
    return this.request("/health");
  }

  budget(): Promise<BudgetInfo> {
    return this.request("/budget");
  }

  profiles(): Promise<string[]> {
    return this.request("/profiles");
  }

  listTasks(filters?: { project?: string; status?: string }): Promise<TaskIndexRow[]> {
    const params = new URLSearchParams();
    if (filters?.project) params.set("project", filters.project);
    if (filters?.status) params.set("status", filters.status);
    const query = params.toString();
    return this.request(`/tasks${query ? `?${query}` : ""}`);
  }

  createTask(body: TaskCreateBody): Promise<TaskRecord> {
    return this.request("/tasks", { method: "POST", body: JSON.stringify(body) });
  }

  showTask(project: string, taskId: string): Promise<TaskRecord> {
    return this.request(`/tasks/${project}/${taskId}`);
  }

  preflight(project: string, taskId: string): Promise<PreflightReport> {
    return this.request(`/tasks/${project}/${taskId}/preflight`);
  }

  runTask(
    project: string,
    taskId: string,
    opts?: { skipPreflight?: boolean },
  ): Promise<{ queued: boolean }> {
    return this.request(`/tasks/${project}/${taskId}/run`, {
      method: "POST",
      body: JSON.stringify({ skip_preflight: opts?.skipPreflight ?? false }),
    });
  }

  cancelTask(
    project: string,
    taskId: string,
  ): Promise<{ canceling?: boolean; canceled?: boolean }> {
    return this.request(`/tasks/${project}/${taskId}/cancel`, { method: "POST" });
  }

  wsUrl(): string {
    const ws = this.baseUrl.replace(/^http/, "ws");
    return `${ws}/ws/events?token=${encodeURIComponent(this.token)}`;
  }
}
