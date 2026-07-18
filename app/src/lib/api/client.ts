import type {
  ArtifactListItem,
  AsrEnginesInfo,
  AsrStatus,
  AsrTestResult,
  DubbingStatus,
  DubbingTestResult,
  PdfEngineStatus,
  PdfEngineTestResult,
  AssistantMessageDoc,
  AssistantReply,
  AssistantSessionRow,
  BudgetInfo,
  ChannelConfigDoc,
  CoreConfigDoc,
  McpServerStatus,
  NotifyTestResult,
  PersistedEvent,
  PreflightReport,
  ProfileInfo,
  ProposalDoc,
  ProviderConfigDoc,
  ProviderTestResult,
  SkillInfo,
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
  // Per-task LLM override written into the task's LLM stage params.
  provider?: string;
  model?: string;
  // Per-task ASR engine override written into asr stage params.
  asr_engine?: string;
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

  testProvider(config: ProviderConfigDoc, model?: string): Promise<ProviderTestResult> {
    return this.request("/config/providers/test", {
      method: "POST",
      body: JSON.stringify({ config, model }),
    });
  }

  profiles(): Promise<string[]> {
    return this.request("/profiles");
  }

  profilesDetailed(): Promise<ProfileInfo[]> {
    return this.request("/profiles/detailed");
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

  // Per-task LLM override; empty strings restore the follow-default state.
  setTaskModel(
    project: string,
    taskId: string,
    provider: string,
    model: string,
  ): Promise<TaskRecord> {
    return this.request(`/tasks/${project}/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ provider, model }),
    });
  }

  // Per-task ASR engine; an empty string removes the override.
  setTaskAsrEngine(
    project: string,
    taskId: string,
    engine: string,
  ): Promise<TaskRecord> {
    return this.request(`/tasks/${project}/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ asr_engine: engine }),
    });
  }

  deleteTask(project: string, taskId: string): Promise<{ deleted: boolean }> {
    return this.request(`/tasks/${project}/${taskId}`, { method: "DELETE" });
  }

  getAsrStatus(model: string): Promise<AsrStatus> {
    return this.request(`/asr/status?model=${encodeURIComponent(model)}`);
  }

  getAsrEngines(macosProbe = false): Promise<AsrEnginesInfo> {
    return this.request(`/asr/engines${macosProbe ? "?macos_probe=true" : ""}`);
  }

  downloadMacosAssets(locale: string): Promise<{ downloading: boolean; locale: string }> {
    return this.request("/asr/macos/assets", {
      method: "POST",
      body: JSON.stringify({ locale }),
    });
  }

  testAsrEngine(body: {
    engine: string;
    model?: string;
    locale?: string;
  }): Promise<AsrTestResult> {
    return this.request("/asr/test", { method: "POST", body: JSON.stringify(body) });
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

  getDubbingStatus(): Promise<DubbingStatus> {
    return this.request("/dubbing/status");
  }

  installDubbingEngine(): Promise<{ installing: boolean }> {
    return this.request("/dubbing/install", { method: "POST" });
  }

  testDubbingEngine(): Promise<DubbingTestResult> {
    return this.request("/dubbing/test", { method: "POST" });
  }

  getPdfEngineStatus(): Promise<PdfEngineStatus> {
    return this.request("/pdf/status");
  }

  installPdfEngine(): Promise<{ installing: boolean }> {
    return this.request("/pdf/install", { method: "POST" });
  }

  testPdfEngine(): Promise<PdfEngineTestResult> {
    return this.request("/pdf/test", { method: "POST" });
  }

  getMcpStatus(): Promise<McpServerStatus[]> {
    return this.request("/mcp/status");
  }

  reloadMcp(): Promise<McpServerStatus[]> {
    return this.request("/mcp/reload", { method: "POST" });
  }

  listSkills(): Promise<SkillInfo[]> {
    return this.request("/skills");
  }

  getSkill(name: string): Promise<{ name: string; content: string }> {
    return this.request(`/skills/${encodeURIComponent(name)}`);
  }

  putSkill(
    name: string,
    content: string,
  ): Promise<{ saved: boolean; confirmation_reset: boolean }> {
    return this.request(`/skills/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    });
  }

  createSkill(name: string): Promise<{ created: string }> {
    return this.request("/skills", { method: "POST", body: JSON.stringify({ name }) });
  }

  importSkill(content: string): Promise<{ created: string }> {
    return this.request("/skills/import", {
      method: "POST",
      body: JSON.stringify({ content }),
    });
  }

  deleteSkill(name: string): Promise<{ deleted: boolean }> {
    return this.request(`/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
  }

  listProposals(status?: string): Promise<ProposalDoc[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return this.request(`/proposals${query}`);
  }

  approveProposal(id: string): Promise<CoreConfigDoc> {
    return this.request(`/proposals/${encodeURIComponent(id)}/approve`, {
      method: "POST",
    });
  }

  rejectProposal(id: string): Promise<ProposalDoc> {
    return this.request(`/proposals/${encodeURIComponent(id)}/reject`, {
      method: "POST",
    });
  }

  sendAssistantMessage(
    text: string,
    opts?: { editIndex?: number; images?: string[] },
  ): Promise<AssistantReply> {
    return this.request("/assistant/message", {
      method: "POST",
      body: JSON.stringify({
        text,
        edit_index: opts?.editIndex,
        images: opts?.images,
      }),
    });
  }

  uploadAssistantAttachment(mime: string, dataBase64: string): Promise<{ path: string }> {
    return this.request("/assistant/attachments", {
      method: "POST",
      body: JSON.stringify({ mime, data_base64: dataBase64 }),
    });
  }

  getAssistantHistory(): Promise<AssistantMessageDoc[]> {
    return this.request("/assistant/history");
  }

  clearAssistant(): Promise<{ cleared: boolean }> {
    return this.request("/assistant/clear", { method: "POST" });
  }

  listAssistantSessions(): Promise<AssistantSessionRow[]> {
    return this.request("/assistant/sessions");
  }

  createAssistantSession(): Promise<{ id: string }> {
    return this.request("/assistant/sessions", { method: "POST" });
  }

  activateAssistantSession(id: string): Promise<{ active: string }> {
    return this.request(`/assistant/sessions/${encodeURIComponent(id)}/activate`, {
      method: "POST",
    });
  }

  archiveAssistantSession(id: string, archived: boolean): Promise<{ archived: boolean }> {
    return this.request(`/assistant/sessions/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ archived }),
    });
  }

  deleteAssistantSession(id: string): Promise<{ deleted: boolean }> {
    return this.request(`/assistant/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
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
