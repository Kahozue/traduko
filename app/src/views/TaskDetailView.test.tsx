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
      onOpenSubtitleEditor={() => {}}
      onOpenStyleEditor={() => {}}
    />, {
    api,
  });
  await waitFor(() => expect(screen.getByText("t1")).toBeInTheDocument());
  expect(screen.getByText("ingest_subtitle")).toBeInTheDocument();
  expect(screen.getByText("translate")).toBeInTheDocument();
  expect(screen.getByText("/tmp/in.srt")).toBeInTheDocument();
});

test("run button queues the task", async () => {
  const runTask = vi.fn().mockResolvedValue({ queued: true });
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task), runTask };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenSubtitleEditor={() => {}}
      onOpenStyleEditor={() => {}}
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
      onOpenSubtitleEditor={() => {}}
      onOpenStyleEditor={() => {}}
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

test("cancel button cancels the task", async () => {
  const cancelTask = vi.fn().mockResolvedValue({ canceled: true });
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task), cancelTask };
  renderWithConnection(<TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenSubtitleEditor={() => {}}
      onOpenStyleEditor={() => {}}
    />, {
    api,
  });
  await waitFor(() => expect(screen.getByText("取消任務")).toBeEnabled());
  await userEvent.click(screen.getByText("取消任務"));
  await waitFor(() => expect(cancelTask).toHaveBeenCalledWith("default", "t1"));
});

test("shows checkpoint banner and opens subtitle editor when waiting_review", async () => {
  const onOpenSubtitleEditor = vi.fn();
  const waiting: TaskRecord = { ...task, status: "waiting_review" };
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(waiting) };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenSubtitleEditor={onOpenSubtitleEditor}
      onOpenStyleEditor={() => {}}
    />,
    { api },
  );
  expect(await screen.findByText("任務停於人工檢查點")).toBeInTheDocument();
  await userEvent.click(screen.getByText("開啟字幕編輯器"));
  expect(onOpenSubtitleEditor).toHaveBeenCalled();
});

test("style editor entry opens from the header actions", async () => {
  const onOpenStyleEditor = vi.fn();
  const api: Partial<ApiClient> = { showTask: vi.fn().mockResolvedValue(task) };
  renderWithConnection(
    <TaskDetailView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenSubtitleEditor={() => {}}
      onOpenStyleEditor={onOpenStyleEditor}
    />,
    { api },
  );
  await userEvent.click(await screen.findByText("字幕樣式"));
  expect(onOpenStyleEditor).toHaveBeenCalled();
});
