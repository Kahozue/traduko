import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({
  convertFileSrc: (path: string) => `asset://localhost/${path}`,
}));

import type { ApiClient } from "../lib/api/client";
import { ApiError } from "../lib/api/client";
import type { TaskRecord } from "../lib/api/types";
import { renderWithConnection } from "../test/helpers";
import { TaskDetailView } from "./TaskDetailView";

const task: TaskRecord = {
  schema_version: 1,
  id: "t1",
  project: "default",
  input_path: "/tmp/in.srt",
  profile: "subtitle-translate",
  name: null,
  status: "pending",
  stages: [
    {
      type: "ingest_subtitle",
      status: "completed",
      params: {},
      pause_after: false,
      artifacts: [],
      error: null,
    },
    {
      type: "translate",
      status: "pending",
      params: {},
      pause_after: false,
      artifacts: [],
      error: null,
    },
  ],
  created_at: "2026-07-16T10:00:00+00:00",
  updated_at: "2026-07-16T10:00:00+00:00",
  glossary: { global_ids: [], use_task: false, asr_mode: "auto" },
};

test("renders stages and metadata", async () => {
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task) };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />, {
    api,
  });
  await waitFor(() => expect(screen.getAllByText("t1").length).toBeGreaterThan(0));
  expect(screen.getByText("讀入字幕")).toBeInTheDocument();
  expect(screen.getByText("翻譯")).toBeInTheDocument();
  expect(screen.queryByText("/tmp/in.srt")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "詳細資訊" }));
  expect(screen.getByText("/tmp/in.srt")).toBeInTheDocument();
});

test("run button queues the task", async () => {
  const runTask = vi.fn().mockResolvedValue({ queued: true });
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task), runTask };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />, {
    api,
  });
  await waitFor(() => expect(screen.getByText("執行")).toBeEnabled());
  await userEvent.click(screen.getByText("執行"));
  await waitFor(() =>
    expect(runTask).toHaveBeenCalledWith("default", "t1", { skipPreflight: false }),
  );
});

test("completed task main button reruns instead of running", async () => {
  const completed = { ...task, status: "completed" as const };
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(completed) };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  const rerunBtn = await screen.findByRole("button", { name: "重新執行" });
  expect(rerunBtn).toBeEnabled();
  expect(screen.queryByRole("button", { name: "執行" })).not.toBeInTheDocument();
});

test("rerun confirmation dialog reruns the task on confirm", async () => {
  const completed = { ...task, status: "completed" as const };
  const rerunTask = vi.fn().mockResolvedValue({ queued: true });
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(completed),
    rerunTask,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  await userEvent.click(await screen.findByRole("button", { name: "重新執行" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(/會被覆蓋/)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "重新執行" }));
  await waitFor(() =>
    expect(rerunTask).toHaveBeenCalledWith("default", "t1", { skipPreflight: false }),
  );
});

test("rerun confirmation dialog aborts on cancel", async () => {
  const completed = { ...task, status: "completed" as const };
  const rerunTask = vi.fn().mockResolvedValue({ queued: true });
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(completed),
    rerunTask,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  await userEvent.click(await screen.findByRole("button", { name: "重新執行" }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "取消" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(rerunTask).not.toHaveBeenCalled();
});

test("rerun preflight failure skips through the rerun endpoint", async () => {
  const completed = { ...task, status: "completed" as const };
  const detail = {
    error: "preflight failed",
    checks: [{ name: "input", level: "fail", message: "input missing" }],
  };
  const rerunTask = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(409, detail))
    .mockResolvedValueOnce({ queued: true });
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(completed),
    rerunTask,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  await userEvent.click(await screen.findByRole("button", { name: "重新執行" }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "重新執行" }));
  await waitFor(() => expect(screen.getByText("預檢未通過")).toBeInTheDocument());
  await userEvent.click(screen.getByText("略過預檢並執行"));
  await waitFor(() =>
    expect(rerunTask).toHaveBeenLastCalledWith("default", "t1", { skipPreflight: true }),
  );
});

test("preflight failure offers skip and re-run", async () => {
  const detail = {
    error: "preflight failed",
    checks: [{ name: "input", level: "fail", message: "input missing" }],
  };
  const runTask = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(409, detail))
    .mockResolvedValueOnce({ queued: true });
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task), runTask };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />, {
    api,
  });
  await waitFor(() => expect(screen.getByText("執行")).toBeEnabled());
  await userEvent.click(screen.getByText("執行"));
  await waitFor(() => expect(screen.getByText("預檢未通過")).toBeInTheDocument());
  expect(screen.getByText("input missing")).toBeInTheDocument();
  await userEvent.click(screen.getByText("略過預檢並執行"));
  await waitFor(() =>
    expect(runTask).toHaveBeenLastCalledWith("default", "t1", { skipPreflight: true }),
  );
});

test("missing ASR model offers download-and-run", async () => {
  const detail = {
    error: "preflight failed",
    checks: [{ name: "asr model", level: "fail", message: "model 'small' is not downloaded yet" }],
  };
  const runTask = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(409, detail))
    .mockResolvedValueOnce({ queued: true });
  const downloadAsrModel = vi.fn().mockResolvedValue({ downloading: true, model: "small" });
  const getAsrStatus = vi.fn().mockResolvedValue({
    package: true,
    model: "small",
    cached: true,
    state: "done",
    downloading: false,
    downloaded_mb: 484,
    error: null,
  });
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(task),
    runTask,
    downloadAsrModel,
    getAsrStatus,
  };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />, {
    api,
  });
  await waitFor(() => expect(screen.getByText("執行")).toBeEnabled());
  await userEvent.click(screen.getByText("執行"));
  await waitFor(() => expect(screen.getByText("預檢未通過")).toBeInTheDocument());
  await userEvent.click(screen.getByText("下載模型並執行"));
  await waitFor(() => expect(downloadAsrModel).toHaveBeenCalledWith("small"));
  await waitFor(() =>
    expect(runTask).toHaveBeenLastCalledWith("default", "t1", { skipPreflight: false }),
  );
});

test("completed task lists outputs and enables the subtitle editor", async () => {
  const completed = { ...task, status: "completed" as const };
  const listArtifacts = vi.fn().mockResolvedValue([
    { file: "06-translation.json", index: 6, name: "translation.json", schema_version: 1, size: 2048, mtime: 1 },
    { file: "07-output.srt", index: 7, name: "output.srt", schema_version: null, size: 4096, mtime: 2 },
  ]);
  const onOpenEditor = vi.fn();
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(completed),
    listArtifacts,
  };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={onOpenEditor}
    />, {
    api,
  });
  await waitFor(() => expect(screen.getByText("07-output.srt")).toBeInTheDocument());
  expect(screen.queryByText("06-translation.json")).not.toBeInTheDocument();
  expect(screen.getByText("在 Finder 顯示")).toBeInTheDocument();
  const editorButton = screen.getByRole("button", { name: "字幕編輯器" });
  expect(editorButton).toBeEnabled();
  await userEvent.click(editorButton);
  expect(onOpenEditor).toHaveBeenCalledWith("subtitle");
});

test("subtitle editor entry is disabled without a translation artifact", async () => {
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(task),
    listArtifacts: vi.fn().mockResolvedValue([]),
  };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />, {
    api,
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "字幕編輯器" })).toBeDisabled(),
  );
});

test("cancel button cancels the task", async () => {
  const cancelTask = vi.fn().mockResolvedValue({ canceled: true });
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task), cancelTask };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />, {
    api,
  });
  await waitFor(() => expect(screen.getByText("取消")).toBeEnabled());
  await userEvent.click(screen.getByText("取消"));
  await waitFor(() => expect(cancelTask).toHaveBeenCalledWith("default", "t1"));
});

test("shows checkpoint banner and opens subtitle editor when waiting_review", async () => {
  const onOpenEditor = vi.fn();
  const waiting: TaskRecord = { ...task, status: "waiting_review" };
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(waiting) };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={onOpenEditor}
    />,
    { api },
  );
  expect(await screen.findByText("任務停於人工檢查點")).toBeInTheDocument();
  await userEvent.click(screen.getByText("開啟字幕編輯器"));
  expect(onOpenEditor).toHaveBeenCalledWith("subtitle");
});

const docTask: TaskRecord = {
  ...task,
  profile: "novel-translate",
  stages: [
    { type: "ingest_document", status: "completed", params: {}, pause_after: false, artifacts: [], error: null },
    { type: "translate_chunks", status: "completed", params: {}, pause_after: false, artifacts: [], error: null },
  ],
};

test("document task shows text editor entry and opens document editor", async () => {
  const onOpenEditor = vi.fn();
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue({ ...docTask, status: "completed" }),
    listArtifacts: vi.fn().mockResolvedValue([
      { file: "03-translation.json", index: 3, name: "translation.json", schema_version: 1, size: 1, mtime: 1 },
    ]),
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={onOpenEditor}
    />,
    { api },
  );
  const editorButton = await screen.findByRole("button", { name: "文本編輯器" });
  expect(screen.queryByRole("button", { name: "字幕編輯器" })).not.toBeInTheDocument();
  await waitFor(() => expect(editorButton).toBeEnabled());
  await userEvent.click(editorButton);
  expect(onOpenEditor).toHaveBeenCalledWith("document");
});

test("document task checkpoint banner opens the document editor", async () => {
  const onOpenEditor = vi.fn();
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue({ ...docTask, status: "waiting_review" }),
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={onOpenEditor}
    />,
    { api },
  );
  expect(await screen.findByText("任務停於人工檢查點")).toBeInTheDocument();
  await userEvent.click(screen.getByText("開啟文本編輯器"));
  expect(onOpenEditor).toHaveBeenCalledWith("document");
});

const pdfTask: TaskRecord = {
  ...task,
  profile: "translate-pdf",
  input_path: "/tmp/in.pdf",
  stages: [
    { type: "translate_pdf", status: "pending", params: {}, pause_after: false, artifacts: [], error: null },
  ],
};

test("pdf task shows no subtitle or text editor entry", async () => {
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(pdfTask) };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />,
    { api },
  );
  expect(await screen.findByText("翻譯 PDF")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "字幕編輯器" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "文本編輯器" })).not.toBeInTheDocument();
});

test("repeated document rounds are labeled as retries", async () => {
  const sevenStages = ["ingest_document", "chunk", "translate_chunks", "qc_scan",
    "translate_chunks", "qc_scan", "export_document"].map((type) => ({
    type, status: "completed", params: {}, pause_after: false, artifacts: [], error: null,
  }));
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue({ ...docTask, stages: sevenStages }),
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />,
    { api },
  );
  expect(await screen.findByText("翻譯文件（重試）")).toBeInTheDocument();
  expect(screen.getByText("品質檢測（重試）")).toBeInTheDocument();
  expect(screen.getByText("翻譯文件")).toBeInTheDocument();
});

test("preflight pdf-engine failure shows localized guidance", async () => {
  const detail = {
    error: "preflight failed",
    checks: [{
      name: "stage 1 (translate_pdf): pdf engine",
      level: "fail",
      message: "pdf engine is not installed; install it from the settings document tab",
    }],
  };
  const runTask = vi.fn().mockRejectedValueOnce(new ApiError(409, detail));
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(pdfTask),
    runTask,
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />,
    { api },
  );
  await waitFor(() => expect(screen.getByText("執行")).toBeEnabled());
  await userEvent.click(screen.getByText("執行"));
  await waitFor(() => expect(screen.getByText("預檢未通過")).toBeInTheDocument());
  expect(screen.getByText("PDF 引擎尚未安裝")).toBeInTheDocument();
});

test("renders localized stage labels and named title", async () => {
  const named = { ...task, name: "第三集" };
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(named) };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />,
    { api },
  );
  expect(await screen.findByText("第三集")).toBeInTheDocument();
  expect(screen.getByText("讀入字幕")).toBeInTheDocument();
  expect(screen.queryByText("ingest_subtitle")).not.toBeInTheDocument();
});

test("rename flow calls renameTask", async () => {
  const named = { ...task, name: "第三集" };
  const renameTask = vi.fn().mockResolvedValue({ ...named, name: "改名後" });
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(named),
    renameTask,
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />,
    { api },
  );
  await screen.findByText("第三集");
  await userEvent.click(screen.getByRole("button", { name: "重新命名" }));
  const field = screen.getByDisplayValue("第三集");
  await userEvent.type(field, "X");
  await userEvent.click(screen.getByText("儲存"));
  await waitFor(() => expect(renameTask).toHaveBeenCalledWith("default", "t1", "第三集X"));
});

test("pause button pauses a running task", async () => {
  const running = { ...task, status: "running" as const };
  const pauseTask = vi.fn().mockResolvedValue({ pausing: true });
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(running),
    pauseTask,
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />,
    { api },
  );
  await waitFor(() => expect(screen.getByText("暫停")).toBeEnabled());
  await userEvent.click(screen.getByText("暫停"));
  await waitFor(() => expect(pauseTask).toHaveBeenCalledWith("default", "t1"));
});

test("pause button is disabled when task is not running", async () => {
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task) };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
    />,
    { api },
  );
  await waitFor(() => expect(screen.getByText("暫停")).toBeDisabled());
});

const CONFIG = {
  default_provider: "glm",
  llm_providers: {
    glm: { type: "openai_compat", model: "glm-4" },
    deepseek: { type: "openai_compat", model: "deepseek-chat" },
  },
};

test("model chip shows the effective provider and opens the switcher", async () => {
  const setTaskModel = vi.fn().mockResolvedValue(task);
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(task),
    getConfig: vi.fn().mockResolvedValue(CONFIG),
    setTaskModel,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  // No override on the translate stage: chip shows the resolved default.
  const chip = await screen.findByRole("button", { name: /glm · glm-4/ });
  await userEvent.click(chip);
  await userEvent.selectOptions(screen.getByLabelText("供應商"), "deepseek");
  await userEvent.click(screen.getByRole("button", { name: "套用" }));
  await waitFor(() =>
    expect(setTaskModel).toHaveBeenCalledWith("default", "t1", "deepseek", ""),
  );
});

test("model chip reset restores follow-default", async () => {
  const overridden: TaskRecord = {
    ...task,
    stages: task.stages.map((stage) =>
      stage.type === "translate"
        ? { ...stage, params: { provider: "deepseek", model: "deepseek-reasoner" } }
        : stage,
    ),
  };
  const setTaskModel = vi.fn().mockResolvedValue(overridden);
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(overridden),
    getConfig: vi.fn().mockResolvedValue(CONFIG),
    setTaskModel,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  const chip = await screen.findByRole("button", { name: /deepseek · deepseek-reasoner/ });
  await userEvent.click(chip);
  await userEvent.click(screen.getByRole("button", { name: "還原自動" }));
  await waitFor(() =>
    expect(setTaskModel).toHaveBeenCalledWith("default", "t1", "", ""),
  );
});

test("model chip is locked while the task runs and engine chip shows", async () => {
  const running: TaskRecord = {
    ...task,
    status: "running",
    stages: [
      {
        type: "asr",
        status: "running",
        params: { provider: "faster_whisper" },
        pause_after: false,
        artifacts: [],
        error: null,
      },
      ...task.stages,
    ],
  };
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(running),
    getConfig: vi.fn().mockResolvedValue(CONFIG),
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  const chip = await screen.findByRole("button", { name: /glm · glm-4/ });
  expect(chip).toBeDisabled();
  const asrChip = screen.getByRole("button", { name: /ASR · faster-whisper/ });
  expect(asrChip).toBeDisabled();
});

test("asr chip switches the engine in place", async () => {
  const audioTask: TaskRecord = {
    ...task,
    stages: [
      {
        type: "asr",
        status: "pending",
        params: { engine: "auto_audio" },
        pause_after: false,
        artifacts: [],
        error: null,
      },
    ],
  };
  const setTaskAsrEngine = vi.fn().mockResolvedValue(audioTask);
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(audioTask),
    getConfig: vi.fn().mockResolvedValue(CONFIG),
    setTaskAsrEngine,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  const chip = await screen.findByRole("button", { name: /ASR · 自動/ });
  await userEvent.click(chip);
  await userEvent.selectOptions(screen.getByLabelText("語音辨識引擎"), "openai_gpt4o");
  await userEvent.click(screen.getByRole("button", { name: "套用" }));
  await waitFor(() =>
    expect(setTaskAsrEngine).toHaveBeenCalledWith("default", "t1", "openai_gpt4o"),
  );
});

test("voice chip switches the dubbing mode in place", async () => {
  const dubTask: TaskRecord = {
    ...task,
    stages: [
      ...task.stages,
      {
        type: "tts_synthesize",
        status: "pending",
        params: {},
        pause_after: false,
        artifacts: [],
        error: null,
      },
    ],
  };
  const setTaskVoiceMode = vi.fn().mockResolvedValue(dubTask);
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(dubTask),
    getConfig: vi.fn().mockResolvedValue(CONFIG),
    setTaskVoiceMode,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  const chip = await screen.findByRole("button", { name: /VoxCPM2 · 克隆原聲/ });
  await userEvent.click(chip);
  await userEvent.selectOptions(screen.getByLabelText("聲音模式"), "design");
  await userEvent.type(screen.getByLabelText("聲音描述"), "沉穩男聲");
  await userEvent.click(screen.getByRole("button", { name: "套用" }));
  await waitFor(() =>
    expect(setTaskVoiceMode).toHaveBeenCalledWith("default", "t1", "design", "沉穩男聲"),
  );
});

test("voice chip reflects the preview mode and resets to clone", async () => {
  const dubTask: TaskRecord = {
    ...task,
    stages: [
      {
        type: "tts_synthesize",
        status: "pending",
        params: { voice_mode: "preview" },
        pause_after: false,
        artifacts: [],
        error: null,
      },
    ],
  };
  const setTaskVoiceMode = vi.fn().mockResolvedValue(dubTask);
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(dubTask),
    getConfig: vi.fn().mockResolvedValue(CONFIG),
    setTaskVoiceMode,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  const chip = await screen.findByRole("button", { name: /系統語音預覽/ });
  await userEvent.click(chip);
  await userEvent.click(screen.getByRole("button", { name: "還原自動" }));
  await waitFor(() =>
    expect(setTaskVoiceMode).toHaveBeenCalledWith("default", "t1", "", ""),
  );
});

// --- pipeline switches (v3_5-04) --------------------------------------------

function stageOf(type: string, status: TaskRecord["stages"][number]["status"] = "pending") {
  return { type, status, params: {}, pause_after: false, artifacts: [], error: null };
}

const audioTask: TaskRecord = {
  ...task,
  profile: "audio-translate",
  stages: [
    stageOf("extract_audio"),
    stageOf("asr"),
    stageOf("segment"),
    stageOf("translate"),
    stageOf("proofread"),
    stageOf("export_transcript"),
    stageOf("export_subtitles"),
  ],
  switches: { translate: true, diarize: null, dub: null },
};

function renderTask(record: TaskRecord, api: Partial<ApiClient> = {}) {
  const merged: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(record),
    ...api,
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api: merged },
  );
  return merged;
}

test("audio task renders its applicable pipeline switches", async () => {
  renderTask(audioTask);
  const group = await screen.findByRole("group", { name: "管線開關" });
  expect(within(group).getByRole("button", { name: /翻譯/ })).toBeInTheDocument();
  expect(within(group).getByRole("button", { name: /配音/ })).toBeInTheDocument();
  // No diarize stage yet, but the task transcribes, so the switch renders
  // and turning it on inserts the stage (spec 4-(3), core-side append).
  expect(within(group).getByRole("button", { name: /說話人分離/ })).toBeInTheDocument();
});

test("an stt-only task can turn on speaker separation", async () => {
  const sttTask: TaskRecord = {
    ...task,
    profile: "audio-transcribe",
    input_path: "/tmp/talk.mp3",
    stages: [stageOf("extract_audio"), stageOf("asr"), stageOf("export_transcript")],
    switches: { translate: null, diarize: null, dub: null },
  };
  const patchTaskSwitches = vi.fn().mockResolvedValue(sttTask);
  renderTask(sttTask, { patchTaskSwitches });
  const group = await screen.findByRole("group", { name: "管線開關" });
  const chip = within(group).getByRole("button", { name: /說話人分離/ });
  expect(chip).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(chip);
  await waitFor(() =>
    expect(patchTaskSwitches).toHaveBeenCalledWith("default", "t1", { diarize: true }),
  );
});

test("a task with nothing to transcribe hides the speaker separation switch", async () => {
  // A subtitle task has no audio: the core answers 409, so no dead chip.
  renderTask({
    ...task,
    input_path: "/tmp/in.srt",
    stages: [stageOf("ingest_subtitle"), stageOf("translate")],
  });
  await screen.findAllByText("t1");
  expect(screen.queryByRole("button", { name: /說話人分離/ })).toBeNull();
});

test("toggling a switch PATCHes the switches endpoint", async () => {
  const patchTaskSwitches = vi
    .fn()
    .mockResolvedValue({ ...audioTask, switches: { translate: false, diarize: null, dub: null } });
  renderTask(audioTask, { patchTaskSwitches });
  const group = await screen.findByRole("group", { name: "管線開關" });
  await userEvent.click(within(group).getByRole("button", { name: /翻譯/ }));
  await waitFor(() =>
    expect(patchTaskSwitches).toHaveBeenCalledWith("default", "t1", { translate: false }),
  );
});

test("skipped stages hide behind the expand button", async () => {
  const record: TaskRecord = {
    ...audioTask,
    stages: [
      stageOf("extract_audio", "completed"),
      stageOf("asr", "completed"),
      stageOf("segment", "completed"),
      stageOf("translate", "skipped"),
      stageOf("proofread", "skipped"),
      stageOf("export_transcript", "completed"),
      stageOf("export_subtitles", "skipped"),
    ],
    switches: { translate: false, diarize: null, dub: null },
  };
  renderTask(record);
  await screen.findByRole("group", { name: "管線開關" });
  const stageList = screen.getByRole("list", { name: "階段" });
  expect(within(stageList).queryByText("AI 校對")).toBeNull();
  const expand = screen.getByRole("button", { name: "含 3 步已跳過" });
  await userEvent.click(expand);
  expect(within(stageList).getByText("AI 校對")).toBeInTheDocument();
  expect(within(stageList).getAllByText("已略過").length).toBe(3);
});

test("switches lock while the task runs", async () => {
  renderTask({ ...audioTask, status: "running" });
  const group = await screen.findByRole("group", { name: "管線開關" });
  expect(within(group).getByRole("button", { name: /翻譯/ })).toBeDisabled();
  expect(within(group).getByRole("button", { name: /配音/ })).toBeDisabled();
});

test("a video-file input renders the inline video player", async () => {
  renderTask({ ...task, input_path: "/tmp/movie.mp4" });
  await screen.findAllByText("t1");
  const video = document.querySelector("video");
  expect(video).not.toBeNull();
  expect(video).toHaveAttribute("src", "asset://localhost//tmp/movie.mp4");
});

test("an audio-file input renders the inline audio player", async () => {
  renderTask({ ...task, input_path: "/tmp/voice.wav" });
  await screen.findAllByText("t1");
  expect(document.querySelector("audio")).not.toBeNull();
  expect(document.querySelector("video")).toBeNull();
});

test("a subtitle input renders no player", async () => {
  renderTask(task);
  await screen.findAllByText("t1");
  expect(document.querySelector("video")).toBeNull();
  expect(document.querySelector("audio")).toBeNull();
});

test("dub button stays disabled until a transcript artifact exists", async () => {
  const dubTask: TaskRecord = {
    ...task,
    profile: "av-dub",
    input_path: "/tmp/in.mp4",
    stages: [
      { type: "extract_audio", status: "completed", params: {}, pause_after: false, artifacts: [], error: null },
      { type: "asr", status: "completed", params: {}, pause_after: false, artifacts: [], error: null },
      { type: "diarize", status: "pending", params: {}, pause_after: false, artifacts: [], error: null },
      { type: "tts_synthesize", status: "pending", params: {}, pause_after: false, artifacts: [], error: null },
    ],
  };
  const onOpenDub = vi.fn();
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(dubTask),
    listArtifacts: vi.fn().mockResolvedValue([]),
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} onOpenDub={onOpenDub} />,
    { api },
  );
  const btn = await screen.findByRole("button", { name: /配音工作室/ });
  expect(btn).toBeDisabled();
  expect(btn.getAttribute("title")).toMatch(/完成轉錄/);
});

test("dub button enables and opens the studio once asr artifact exists", async () => {
  const dubTask: TaskRecord = {
    ...task,
    profile: "av-dub",
    input_path: "/tmp/in.mp4",
    stages: [
      { type: "extract_audio", status: "completed", params: {}, pause_after: false, artifacts: [], error: null },
      { type: "asr", status: "completed", params: {}, pause_after: false, artifacts: [], error: null },
      { type: "diarize", status: "pending", params: {}, pause_after: false, artifacts: [], error: null },
      { type: "tts_synthesize", status: "pending", params: {}, pause_after: false, artifacts: [], error: null },
    ],
  };
  const onOpenDub = vi.fn();
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(dubTask),
    listArtifacts: vi.fn().mockResolvedValue([
      { file: "05-asr.json", index: 5, name: "asr.json", schema_version: 1, size: 1024, mtime: 1 },
    ]),
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} onOpenDub={onOpenDub} />,
    { api },
  );
  const btn = await screen.findByRole("button", { name: /配音工作室/ });
  await waitFor(() => expect(btn).toBeEnabled());
  await userEvent.click(btn);
  expect(onOpenDub).toHaveBeenCalled();
});

test("the export studio entry appears for media tasks and opens the studio", async () => {
  const mediaTask: TaskRecord = { ...task, input_path: "/tmp/in.mp4" };
  const onOpenExport = vi.fn();
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(mediaTask),
    listArtifacts: vi.fn().mockResolvedValue([]),
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
      onOpenExport={onOpenExport}
    />,
    { api },
  );
  const btn = await screen.findByRole("button", { name: /匯出工作室/ });
  await userEvent.click(btn);
  expect(onOpenExport).toHaveBeenCalled();
});

test("the export studio entry is hidden for subtitle tasks", async () => {
  const subtitleTask: TaskRecord = { ...task, input_path: "/tmp/in.srt" };
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(subtitleTask),
    listArtifacts: vi.fn().mockResolvedValue([]),
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
      onOpenExport={() => {}}
    />,
    { api },
  );
  await screen.findByRole("button", { name: /暫停/ });
  expect(screen.queryByRole("button", { name: /匯出工作室/ })).toBeNull();
});

test("the translation settings entry only appears for tasks with a translate stage", async () => {
  const onOpenTranslation = vi.fn();
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task) };
  const { unmount } = renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
      onOpenTranslation={onOpenTranslation}
    />,
    { api },
  );
  await waitFor(() => expect(screen.getAllByText("t1").length).toBeGreaterThan(0));
  await userEvent.click(screen.getByRole("button", { name: "翻譯設定" }));
  expect(onOpenTranslation).toHaveBeenCalledTimes(1);
  unmount();

  const noTranslate: TaskRecord = {
    ...task,
    stages: [task.stages[0]],
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
      onOpenTranslation={onOpenTranslation}
    />,
    { api: { showTask: vi.fn().mockResolvedValue(noTranslate) } },
  );
  await waitFor(() => expect(screen.getAllByText("t1").length).toBeGreaterThan(0));
  expect(screen.queryByRole("button", { name: "翻譯設定" })).toBeNull();
});

test("the export studio entry stays for a video task with no export stage", async () => {
  // Regression guard: keying the entry off produced stages alone would hide
  // it for av-default, where a video goes in and only subtitles come out.
  const avDefault: TaskRecord = {
    ...task,
    input_path: "/tmp/in.mp4",
    profile: "av-default",
    stages: [
      {
        type: "extract_audio",
        status: "completed",
        params: {},
        pause_after: false,
        artifacts: [],
        error: null,
      },
      {
        type: "export_subtitles",
        status: "completed",
        params: {},
        pause_after: false,
        artifacts: [],
        error: null,
      },
    ],
  };
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(avDefault),
    listArtifacts: vi.fn().mockResolvedValue([]),
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
      onOpenExport={() => {}}
    />,
    { api },
  );
  expect(await screen.findByRole("button", { name: /匯出工作室/ })).toBeInTheDocument();
});

// --- studio row (v3_5-11 M1) ------------------------------------------------

test("internal working files stay out of the outputs list", async () => {
  // 05-mix.filter is an ffmpeg filter script, not something to open.
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue({ ...task, status: "completed" as const }),
    listArtifacts: vi.fn().mockResolvedValue([
      { file: "05-mix.filter", index: 5, name: "mix.filter", schema_version: null, size: 300, mtime: 1 },
      { file: "06-translation.json", index: 6, name: "translation.json", schema_version: 1, size: 2048, mtime: 2 },
      { file: "07-output.srt", index: 7, name: "output.srt", schema_version: null, size: 4096, mtime: 3 },
      { file: "08-dubbed.m4a", index: 8, name: "dubbed.m4a", schema_version: null, size: 9000, mtime: 4 },
    ]),
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  await waitFor(() => expect(screen.getByText("07-output.srt")).toBeInTheDocument());
  expect(screen.getByText("08-dubbed.m4a")).toBeInTheDocument();
  expect(screen.queryByText("05-mix.filter")).toBeNull();
  expect(screen.queryByText("06-translation.json")).toBeNull();
});

test("studio entries sit in their own row, out of the header run controls", async () => {
  const dubTask: TaskRecord = {
    ...task,
    profile: "av-dub",
    input_path: "/tmp/in.mp4",
    stages: [
      stageOf("extract_audio", "completed"),
      stageOf("asr", "completed"),
      stageOf("translate", "completed"),
      stageOf("diarize", "completed"),
      stageOf("tts_synthesize", "pending"),
    ],
  };
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(dubTask),
    listArtifacts: vi.fn().mockResolvedValue([
      { file: "02-asr.json", index: 2, name: "asr.json", schema_version: 1, size: 1024, mtime: 1 },
    ]),
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
      onOpenGlossary={() => {}}
      onOpenDub={() => {}}
      onOpenExport={() => {}}
      onOpenTranslation={() => {}}
    />,
    { api },
  );
  const row = await screen.findByRole("group", { name: "工作室" });
  for (const name of [
    "字幕編輯器",
    "說話人檢查",
    "配音工作室",
    "匯出工作室",
    "名詞表",
    "翻譯設定",
  ]) {
    expect(within(row).getByRole("button", { name })).toBeInTheDocument();
  }
  // The header keeps only the run controls: at 1280px five buttons plus a
  // long title wrapped, so the editor entries moved into the studio row too.
  const header = document.querySelector("header") as HTMLElement;
  expect(header).not.toBeNull();
  for (const name of [
    "字幕編輯器",
    "說話人檢查",
    "配音工作室",
    "匯出工作室",
    "名詞表",
    "翻譯設定",
  ]) {
    expect(within(header).queryByRole("button", { name })).toBeNull();
  }
  expect(within(header).getByRole("button", { name: "執行" })).toBeInTheDocument();
  expect(within(header).getByRole("button", { name: "暫停" })).toBeInTheDocument();
  expect(within(header).getByRole("button", { name: "取消" })).toBeInTheDocument();
});

test("the export studio entry appears for a compose task", async () => {
  const composeTask: TaskRecord = {
    ...task,
    input_path: "/tmp/lines.srt",
    profile: "audio-compose",
    stages: [
      {
        type: "ingest_transcript",
        status: "completed",
        params: {},
        pause_after: false,
        artifacts: [],
        error: null,
      },
      {
        type: "export_audio",
        status: "completed",
        params: {},
        pause_after: false,
        artifacts: [],
        error: null,
      },
    ],
  };
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(composeTask),
    listArtifacts: vi.fn().mockResolvedValue([]),
  };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenEditor={() => {}}
      onOpenExport={() => {}}
    />,
    { api },
  );
  expect(await screen.findByRole("button", { name: /匯出工作室/ })).toBeInTheDocument();
});

test("outputs are grouped by kind, with audio playing in place", async () => {
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue({ ...task, status: "completed" as const }),
    listArtifacts: vi.fn().mockResolvedValue([
      { file: "07-output.srt", index: 7, name: "output.srt", schema_version: null, size: 4096, mtime: 1 },
      { file: "08-dub-mix.wav", index: 8, name: "dub-mix.wav", schema_version: null, size: 9000, mtime: 2 },
    ]),
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  await waitFor(() => expect(screen.getByText("07-output.srt")).toBeInTheDocument());
  expect(screen.getByRole("heading", { name: "音訊" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "文件" })).toBeInTheDocument();
  // The audio row plays inline, so it offers a transport instead of "open".
  expect(screen.getByRole("button", { name: "播放" })).toBeInTheDocument();
  expect(screen.getByRole("slider", { name: "播放進度" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "開啟" })).toHaveLength(1);
});

test("opening a text output toggles the inline preview", async () => {
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue({ ...task, status: "completed" as const }),
    listArtifacts: vi.fn().mockResolvedValue([
      { file: "07-output.srt", index: 7, name: "output.srt", schema_version: null, size: 4096, mtime: 1 },
    ]),
  };
  renderWithConnection(
    <TaskDetailView project="default" taskId="t1" onBack={() => {}} onOpenEditor={() => {}} />,
    { api },
  );
  await userEvent.click(await screen.findByRole("button", { name: "開啟" }));
  expect(screen.getByRole("button", { name: "放大字級" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "收合" }));
  expect(screen.queryByRole("button", { name: "放大字級" })).toBeNull();
});
