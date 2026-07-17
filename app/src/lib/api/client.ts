import type {
  ArtifactListItem,
  AsrStatus,
  AsrTestResult,
  BudgetInfo,
  ChannelConfigDoc,
  CoreConfigDoc,
  McpServerStatus,
  NotifyTestResult,
  PersistedEvent,
  PreflightReport,
  SubtitleStylePreset,
  SyncReport,
  SyncStatus,
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
  name?: string;
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

  getConfig(): Promise<CoreConfigDoc> {
    return this.request("/config");
  }

  saveConfig(body: CoreConfigDoc): Promise<CoreConfigDoc> {
    return this.request("/config", { method: "PUT", body: JSON.stringify(body) });
  }

  testNotification(channel: ChannelConfigDoc): Promise<NotifyTestResult> {
    return this.request("/config/notifications/test", {
      method: "POST",
      body: JSON.stringify({ channel }),
    });
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

  taskEvents(project: string, taskId: string, limit = 100): Promise<PersistedEvent[]> {
    return this.request(`/tasks/${project}/${taskId}/events?limit=${limit}`);
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

  pauseTask(project: string, taskId: string): Promise<{ pausing: boolean }> {
    return this.request(`/tasks/${project}/${taskId}/pause`, { method: "POST" });
  }

  renameTask(project: string, taskId: string, name: string): Promise<TaskRecord> {
    return this.request(`/tasks/${project}/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
  }

  moveTask(project: string, taskId: string, newProject: string): Promise<TaskRecord> {
    return this.request(`/tasks/${project}/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ project: newProject }),
    });
  }

  deleteTask(project: string, taskId: string): Promise<{ deleted: boolean }> {
    return this.request(`/tasks/${project}/${taskId}`, { method: "DELETE" });
  }

  getAsrStatus(model: string): Promise<AsrStatus> {
    return this.request(`/asr/status?model=${encodeURIComponent(model)}`);
  }

  downloadAsrModel(model: string): Promise<{ downloading: boolean; model: string }> {
    return this.request("/asr/download", {
      method: "POST",
      body: JSON.stringify({ model }),
    });
  }

  testAsr(model: string): Promise<AsrTestResult> {
    return this.request("/asr/test", {
      method: "POST",
      body: JSON.stringify({ model }),
    });
  }

  getMcpStatus(): Promise<McpServerStatus[]> {
    return this.request("/mcp/status");
  }

  reloadMcp(): Promise<McpServerStatus[]> {
    return this.request("/mcp/reload", { method: "POST" });
  }

  listArtifacts(project: string, taskId: string): Promise<ArtifactListItem[]> {
    return this.request(`/tasks/${project}/${taskId}/artifacts`);
  }

  readArtifact<T>(
    project: string,
    taskId: string,
    name: string,
    version = "latest",
  ): Promise<T> {
    return this.request(`/tasks/${project}/${taskId}/artifacts/${name}?version=${version}`);
  }

  saveArtifact(
    project: string,
    taskId: string,
    name: string,
    body: unknown,
  ): Promise<{ file: string; stages_reset: number }> {
    return this.request(`/tasks/${project}/${taskId}/artifacts/${name}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  }

  getStyles(): Promise<Record<string, SubtitleStylePreset>> {
    return this.request("/styles");
  }

  saveStyles(body: Record<string, SubtitleStylePreset>): Promise<{ saved: boolean }> {
    return this.request("/styles", { method: "PUT", body: JSON.stringify(body) });
  }

  async renderFrame(
    project: string,
    taskId: string,
    body: {
      style: Partial<SubtitleStylePreset>;
      text: string;
      width?: number;
      height?: number;
      background?: string;
    },
  ): Promise<Blob> {
    const response = await this.fetchFn(
      `${this.baseUrl}/tasks/${project}/${taskId}/render-frame`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${this.token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      throw new ApiError(response.status, await response.json().catch(() => null));
    }
    return response.blob();
  }

  getSyncStatus(): Promise<SyncStatus> {
    return this.request("/sync/status");
  }

  runSync(): Promise<SyncReport> {
    return this.request("/sync/run", { method: "POST" });
  }

  resolveSyncConflict(
    file: string,
    source: string,
    choice: "local" | "remote",
  ): Promise<{ resolved: boolean }> {
    return this.request("/sync/resolve", {
      method: "POST",
      body: JSON.stringify({ file, source, choice }),
    });
  }

  wsUrl(): string {
    const ws = this.baseUrl.replace(/^http/, "ws");
    return `${ws}/ws/events?token=${encodeURIComponent(this.token)}`;
  }
}
