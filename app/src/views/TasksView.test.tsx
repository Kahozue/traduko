import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ApiClient } from "../lib/api/client";
import { renderWithConnection } from "../test/helpers";
import { TasksView } from "./TasksView";

const rows = [
  {
    id: "20260716-0001",
    project: "default",
    status: "completed" as const,
    profile: "subtitle-translate",
    name: "第三集",
    created_at: "2026-07-16T10:00:00+00:00",
    updated_at: "2026-07-16T10:05:00+00:00",
  },
];

test("lists tasks and opens detail on click", async () => {
  const api: Partial<ApiClient> = { listTasks: vi.fn().mockResolvedValue(rows) };
  const onOpenTask = vi.fn();
  renderWithConnection(<TasksView onOpenTask={onOpenTask} />, { api });
  await waitFor(() => expect(screen.getByText("第三集")).toBeInTheDocument());
  expect(screen.getByText(/20260716-0001/)).toBeInTheDocument();
  expect(within(screen.getByRole("table")).getByText("已完成")).toBeInTheDocument();
  await userEvent.click(screen.getByText("第三集"));
  expect(onOpenTask).toHaveBeenCalledWith("default", "20260716-0001");
});

test("shows first-run guide when there are no tasks", async () => {
  const api: Partial<ApiClient> = { listTasks: vi.fn().mockResolvedValue([]) };
  const onOpenSettings = vi.fn();
  renderWithConnection(
    <TasksView onOpenTask={() => {}} onOpenSettings={onOpenSettings} />,
    { api },
  );
  await waitFor(() => expect(screen.getByText("還沒有任務")).toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: "前往設定" }));
  expect(onOpenSettings).toHaveBeenCalled();
});

test("create signal opens the dialog with a dropped path", async () => {
  const api: Partial<ApiClient> = {
    listTasks: vi.fn().mockResolvedValue([]),
    profiles: vi.fn().mockResolvedValue(["av-default"]),
  };
  renderWithConnection(
    <TasksView onOpenTask={() => {}} createSignal={1} droppedPath="/tmp/movie.mkv" />,
    { api },
  );
  await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  expect(screen.getByDisplayValue("/tmp/movie.mkv")).toBeInTheDocument();
});

test("status filter refetches with filter", async () => {
  const listTasks = vi.fn().mockResolvedValue([]);
  renderWithConnection(<TasksView onOpenTask={() => {}} />, { api: { listTasks } });
  await waitFor(() => expect(listTasks).toHaveBeenCalled());
  await userEvent.selectOptions(screen.getByRole("combobox"), "running");
  await waitFor(() => expect(listTasks).toHaveBeenLastCalledWith({ status: "running" }));
});
