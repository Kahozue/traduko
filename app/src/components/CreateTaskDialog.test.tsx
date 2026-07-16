import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

const openMock = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: (...args: unknown[]) => openMock(...args),
}));

import type { ApiClient } from "../lib/api/client";
import { renderWithConnection } from "../test/helpers";
import { CreateTaskDialog } from "./CreateTaskDialog";

test("picks file, selects profile and submits", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t-new", project: "default" });
  const api: Partial<ApiClient> = {
    profiles: vi.fn().mockResolvedValue(["av-default", "subtitle-translate"]),
    createTask,
  };
  const onCreated = vi.fn();
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={onCreated} />, { api });

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

test("file picker restricts to subtitle and media extensions", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const api: Partial<ApiClient> = { profiles: vi.fn().mockResolvedValue(["av-default"]) };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });
  await userEvent.click(screen.getByText("選擇檔案"));
  const arg = openMock.mock.calls[0][0] as {
    filters?: { extensions: string[] }[];
  };
  const extensions = arg.filters?.[0]?.extensions ?? [];
  expect(extensions).toContain("srt");
  expect(extensions).toContain("mp4");
  expect(extensions).not.toContain("png");
});

test("close button calls onClose", async () => {
  const api: Partial<ApiClient> = { profiles: vi.fn().mockResolvedValue([]) };
  const onClose = vi.fn();
  renderWithConnection(<CreateTaskDialog onClose={onClose} onCreated={() => {}} />, { api });
  await userEvent.click(screen.getByText("取消"));
  expect(onClose).toHaveBeenCalled();
});

test("submits custom task name when provided", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t9", project: "default" });
  const api: Partial<ApiClient> = {
    profiles: vi.fn().mockResolvedValue(["subtitle-translate"]),
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
