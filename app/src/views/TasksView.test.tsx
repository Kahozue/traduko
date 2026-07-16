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

test("shows empty state", async () => {
  const api: Partial<ApiClient> = { listTasks: vi.fn().mockResolvedValue([]) };
  renderWithConnection(<TasksView onOpenTask={() => {}} />, { api });
  await waitFor(() => expect(screen.getByText("尚無任務，點右上角新增")).toBeInTheDocument());
});

test("status filter refetches with filter", async () => {
  const listTasks = vi.fn().mockResolvedValue([]);
  renderWithConnection(<TasksView onOpenTask={() => {}} />, { api: { listTasks } });
  await waitFor(() => expect(listTasks).toHaveBeenCalled());
  await userEvent.selectOptions(screen.getByRole("combobox"), "running");
  await waitFor(() => expect(listTasks).toHaveBeenLastCalledWith({ status: "running" }));
});
