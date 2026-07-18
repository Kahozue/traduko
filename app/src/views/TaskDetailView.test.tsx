import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
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
  await waitFor(() => expect(screen.getByText("取消任務")).toBeEnabled());
  await userEvent.click(screen.getByText("取消任務"));
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
  expect(screen.getByText("faster-whisper")).toBeInTheDocument();
});
