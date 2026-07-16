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

test("close button calls onClose", async () => {
  const api: Partial<ApiClient> = { profiles: vi.fn().mockResolvedValue([]) };
  const onClose = vi.fn();
  renderWithConnection(<CreateTaskDialog onClose={onClose} onCreated={() => {}} />, { api });
  await userEvent.click(screen.getByText("取消"));
  expect(onClose).toHaveBeenCalled();
});
