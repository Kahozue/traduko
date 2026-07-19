import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
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
  {
    id: "20260716-0002",
    project: "anime",
    status: "pending" as const,
    profile: "av-default",
    name: "第四集",
    created_at: "2026-07-16T11:00:00+00:00",
    updated_at: "2026-07-16T11:05:00+00:00",
  },
];

beforeEach(() => {
  localStorage.clear();
});

test("lists tasks and opens detail on click", async () => {
  const api: Partial<ApiClient> = { listTasks: vi.fn().mockResolvedValue(rows) };
  const onOpenTask = vi.fn();
  renderWithConnection(<TasksView onOpenTask={onOpenTask} />, { api });
  await waitFor(() => expect(screen.getByText("第三集")).toBeInTheDocument());
  expect(screen.queryByText(/20260716-0001/)).not.toBeInTheDocument();
  expect(
    screen.getAllByText("已完成").some((el) => el.tagName !== "OPTION"),
  ).toBe(true);
  await userEvent.click(screen.getByText("第三集"));
  expect(onOpenTask).toHaveBeenCalledWith("default", "20260716-0001");
});

test("groups tasks by project with counts", async () => {
  const api: Partial<ApiClient> = { listTasks: vi.fn().mockResolvedValue(rows) };
  renderWithConnection(<TasksView onOpenTask={() => {}} />, { api });
  await screen.findByText("第三集");
  expect(screen.getByRole("button", { name: /default/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /anime/ })).toBeInTheDocument();
});

test("collapsing a group hides its rows and persists", async () => {
  const api: Partial<ApiClient> = { listTasks: vi.fn().mockResolvedValue(rows) };
  renderWithConnection(<TasksView onOpenTask={() => {}} />, { api });
  await screen.findByText("第三集");
  await userEvent.click(screen.getByRole("button", { name: /default/ }));
  expect(screen.queryByText("第三集")).not.toBeInTheDocument();
  expect(screen.getByText("第四集")).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem("traduko.tasks.collapsed") ?? "[]")).toEqual([
    "default",
  ]);
});

test("bulk delete asks for confirmation then deletes selected", async () => {
  const deleteTask = vi.fn().mockResolvedValue({ deleted: true });
  const api: Partial<ApiClient> = {
    listTasks: vi.fn().mockResolvedValue(rows),
    deleteTask,
  };
  renderWithConnection(<TasksView onOpenTask={() => {}} />, { api });
  await screen.findByText("第三集");
  await userEvent.click(screen.getByRole("checkbox", { name: "選取 第三集" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "選取 第四集" }));
  expect(screen.getByText(/已選 2/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "刪除" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "永久刪除" }));
  await waitFor(() => expect(deleteTask).toHaveBeenCalledTimes(2));
  expect(deleteTask).toHaveBeenCalledWith("default", "20260716-0001");
  expect(deleteTask).toHaveBeenCalledWith("anime", "20260716-0002");
});

test("move menu moves selection to an existing project", async () => {
  const moveTask = vi.fn().mockResolvedValue({});
  const api: Partial<ApiClient> = {
    listTasks: vi.fn().mockResolvedValue(rows),
    moveTask,
  };
  renderWithConnection(<TasksView onOpenTask={() => {}} />, { api });
  await screen.findByText("第三集");
  await userEvent.click(screen.getByRole("checkbox", { name: "選取 第三集" }));
  await userEvent.click(screen.getByRole("button", { name: "搬移到…" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "anime" }));
  await waitFor(() =>
    expect(moveTask).toHaveBeenCalledWith("default", "20260716-0001", "anime"),
  );
});

test("move menu creates a new category", async () => {
  const moveTask = vi.fn().mockResolvedValue({});
  const api: Partial<ApiClient> = {
    listTasks: vi.fn().mockResolvedValue(rows),
    moveTask,
  };
  renderWithConnection(<TasksView onOpenTask={() => {}} />, { api });
  await screen.findByText("第三集");
  await userEvent.click(screen.getByRole("checkbox", { name: "選取 第三集" }));
  await userEvent.click(screen.getByRole("button", { name: "搬移到…" }));
  await userEvent.type(screen.getByPlaceholderText("新分類名稱"), "電影");
  await userEvent.click(screen.getByRole("button", { name: "搬移" }));
  await waitFor(() =>
    expect(moveTask).toHaveBeenCalledWith("default", "20260716-0001", "電影"),
  );
});

test("dragging a row onto a group header moves it", async () => {
  const moveTask = vi.fn().mockResolvedValue({});
  const api: Partial<ApiClient> = {
    listTasks: vi.fn().mockResolvedValue(rows),
    moveTask,
  };
  const onOpenTask = vi.fn();
  renderWithConnection(<TasksView onOpenTask={onOpenTask} />, { api });
  await screen.findByText("第三集");
  const header = screen.getByTestId("group-header-anime");
  const original = document.elementFromPoint;
  document.elementFromPoint = vi.fn(() => header);
  try {
    const row = screen.getByText("第三集").closest("div[class*='row']")!;
    fireEvent.pointerDown(row, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(window, { clientX: 60, clientY: 120 });
    fireEvent.pointerUp(window, {});
    await waitFor(() =>
      expect(moveTask).toHaveBeenCalledWith("default", "20260716-0001", "anime"),
    );
    // The drag must not also open the task.
    fireEvent.click(row);
    expect(onOpenTask).not.toHaveBeenCalled();
  } finally {
    document.elementFromPoint = original;
  }
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

test("comic domain shows a not-yet-available placeholder instead of the guide", async () => {
  const api: Partial<ApiClient> = { listTasks: vi.fn().mockResolvedValue([]) };
  renderWithConnection(<TasksView onOpenTask={() => {}} taskKind="comic" />, { api });
  await waitFor(() =>
    expect(
      screen.getByText("此任務域尚未開放，漫畫翻譯管線正在規劃中"),
    ).toBeInTheDocument(),
  );
  expect(screen.queryByText("還沒有任務")).not.toBeInTheDocument();
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
