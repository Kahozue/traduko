import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

const openMock = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: (...args: unknown[]) => openMock(...args),
}));

import type { ApiClient } from "../lib/api/client";
import type { ProfileInfo } from "../lib/api/types";
import { renderWithConnection } from "../test/helpers";
import { CreateTaskDialog } from "./CreateTaskDialog";

const DETAILED: ProfileInfo[] = [
  { name: "av-default", kind: "video" },
  { name: "subtitle-translate", kind: "video" },
  { name: "novel-translate", kind: "document" },
];

test("picks file, selects a video profile and submits", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t-new", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    createTask,
  };
  const onCreated = vi.fn();
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={onCreated} />, { api });

  // Video is auto-selected (first kind with profiles); its two profiles show
  // in the combobox.
  await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.srt")).toBeInTheDocument());
  await userEvent.selectOptions(screen.getByRole("combobox"), "subtitle-translate");
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith({
      input_path: "/tmp/in.srt",
      profile: "subtitle-translate",
      project: "default",
    }),
  );
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("default", "t-new"));
});

test("choosing the document type switches to its single profile", async () => {
  openMock.mockResolvedValue("/tmp/novel.md");
  const createTask = vi.fn().mockResolvedValue({ id: "d1", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByRole("button", { name: /文檔/ })).toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: /文檔/ }));
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/novel.md")).toBeInTheDocument());
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({ profile: "novel-translate" }),
    ),
  );
});

test("a task type with no profiles is disabled", async () => {
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });
  await waitFor(() => expect(screen.getByRole("button", { name: /漫畫/ })).toBeDisabled());
});

test("file picker filter name follows the task type", async () => {
  openMock.mockResolvedValue("/tmp/novel.md");
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  // Video is auto-selected first: its filter keeps the subtitle/media name.
  await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() =>
    expect(openMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        filters: [expect.objectContaining({ name: "字幕或影音檔" })],
      }),
    ),
  );

  await userEvent.click(screen.getByRole("button", { name: /文檔/ }));
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() =>
    expect(openMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        filters: [expect.objectContaining({ name: "文件檔" })],
      }),
    ),
  );
});

test("close button calls onClose", async () => {
  const api: Partial<ApiClient> = { profilesDetailed: vi.fn().mockResolvedValue([]) };
  const onClose = vi.fn();
  renderWithConnection(<CreateTaskDialog onClose={onClose} onCreated={() => {}} />, { api });
  await userEvent.click(screen.getByText("取消"));
  expect(onClose).toHaveBeenCalled();
});

test("submits custom task name when provided", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t9", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.srt")).toBeInTheDocument());
  await userEvent.type(screen.getByLabelText("任務名稱"), "第三集");
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(expect.objectContaining({ name: "第三集" })),
  );
});

test("provider and model overrides are sent when chosen", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t2", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    getConfig: vi.fn().mockResolvedValue({
      default_provider: "glm",
      llm_providers: {
        glm: { type: "openai_compat", model: "glm-4" },
        deepseek: { type: "openai_compat", model: "deepseek-chat" },
      },
    }),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByLabelText("供應商")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.srt")).toBeInTheDocument());
  await userEvent.selectOptions(screen.getByLabelText("供應商"), "deepseek");
  await userEvent.type(screen.getByLabelText("模型"), "deepseek-reasoner");
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({ provider: "deepseek", model: "deepseek-reasoner" }),
    ),
  );
});

test("auto provider sends no override fields", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t3", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    getConfig: vi.fn().mockResolvedValue({
      default_provider: "glm",
      llm_providers: { glm: { type: "openai_compat", model: "glm-4" } },
    }),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByLabelText("供應商")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.srt")).toBeInTheDocument());
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() => expect(createTask).toHaveBeenCalled());
  const body = createTask.mock.calls[0][0] as Record<string, unknown>;
  expect(body.provider).toBeUndefined();
  expect(body.model).toBeUndefined();
});
