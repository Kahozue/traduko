import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ApiClient } from "../lib/api/client";
import { renderWithConnection } from "../test/helpers";
import { BudgetView } from "./BudgetView";

test("shows usage and limits", async () => {
  const api: Partial<ApiClient> = {
    budget: vi.fn().mockResolvedValue({
      month_usd: 2.5,
      task_usd_limit: 1,
      monthly_usd_limit: 10,
      tasks: [],
    }),
  };
  renderWithConnection(<BudgetView />, { api });
  await waitFor(() => expect(screen.getByText("$2.50")).toBeInTheDocument());
  expect(screen.getByText("$1.00")).toBeInTheDocument();
  expect(screen.getByText("$10.00")).toBeInTheDocument();
  expect(screen.getByText("尚無花費紀錄")).toBeInTheDocument();
});

test("shows unlimited label for null limits", async () => {
  const api: Partial<ApiClient> = {
    budget: vi.fn().mockResolvedValue({
      month_usd: 0,
      task_usd_limit: null,
      monthly_usd_limit: null,
      tasks: [],
    }),
  };
  renderWithConnection(<BudgetView />, { api });
  await waitFor(() => expect(screen.getAllByText("未設上限")).toHaveLength(2));
});

test("formats the monthly progress readout as currency, not raw floats", async () => {
  const api: Partial<ApiClient> = {
    budget: vi.fn().mockResolvedValue({
      month_usd: 0.04703399999999999,
      task_usd_limit: null,
      monthly_usd_limit: 100,
      tasks: [],
    }),
  };
  renderWithConnection(<BudgetView />, { api });
  await waitFor(() => expect(screen.getByText("$0.05 / $100.00")).toBeInTheDocument());
  expect(screen.queryByText(/0\.047033/)).not.toBeInTheDocument();
});

test("charts spend by model with a donut total and ranking bars", async () => {
  const api: Partial<ApiClient> = {
    budget: vi.fn().mockResolvedValue({
      month_usd: 3,
      task_usd_limit: null,
      monthly_usd_limit: null,
      tasks: [],
      models: [
        { model: "gpt-4o", usd: 6, calls: 12 },
        { model: "whisper-1", usd: 4, calls: 3 },
      ],
    }),
  };
  renderWithConnection(<BudgetView />, { api });
  await waitFor(() => expect(screen.getByText("gpt-4o")).toBeInTheDocument());
  expect(screen.getByText("whisper-1")).toBeInTheDocument();
  // Ranking rows carry value and share; the donut centre shows the total.
  expect(screen.getByText("$6.00")).toBeInTheDocument();
  expect(screen.getByText("60%")).toBeInTheDocument();
  expect(screen.getByText("40%")).toBeInTheDocument();
  expect(screen.getByText("$10.00")).toBeInTheDocument();
});

test("hovering a model reveals a spend detail tooltip", async () => {
  const api: Partial<ApiClient> = {
    budget: vi.fn().mockResolvedValue({
      month_usd: 3,
      task_usd_limit: null,
      monthly_usd_limit: null,
      tasks: [],
      models: [
        { model: "gpt-4o", usd: 6, calls: 12 },
        { model: "whisper-1", usd: 4, calls: 3 },
      ],
    }),
  };
  renderWithConnection(<BudgetView />, { api });
  const row = (await screen.findByText("gpt-4o")).closest("li");
  expect(row).not.toBeNull();
  fireEvent.mouseEnter(row!);
  // Tooltip shows precise share and the call count as further detail.
  expect(screen.getByText("60.0%")).toBeInTheDocument();
  expect(screen.getByText("12")).toBeInTheDocument();
});

test("filters spend by time range", async () => {
  const budget = vi.fn().mockResolvedValue({
    month_usd: 0,
    task_usd_limit: null,
    monthly_usd_limit: null,
    tasks: [],
    models: [],
  });
  renderWithConnection(<BudgetView />, { api: { budget } });
  // Wait for the view (and its range filter) to render.
  await screen.findByRole("button", { name: "本月" });
  // Default is all-time: no range bounds.
  expect(budget).toHaveBeenLastCalledWith({});
  fireEvent.click(screen.getByRole("button", { name: "本月" }));
  await waitFor(() => {
    const calls = budget.mock.calls;
    expect(calls[calls.length - 1][0]).toEqual(
      expect.objectContaining({ from: expect.any(String) }),
    );
  });
});

test("lists per-task spend with names", async () => {
  const api: Partial<ApiClient> = {
    budget: vi.fn().mockResolvedValue({
      month_usd: 3,
      task_usd_limit: null,
      monthly_usd_limit: null,
      tasks: [
        { task_id: "t-1", project: "anime", name: "第七話", usd: 2.25 },
        { task_id: "t-2", project: "default", name: null, usd: 0.75 },
      ],
    }),
  };
  renderWithConnection(<BudgetView />, { api });
  await waitFor(() => expect(screen.getByText("第七話")).toBeInTheDocument());
  expect(screen.getByText("$2.25")).toBeInTheDocument();
  expect(screen.getByText("t-2")).toBeInTheDocument();
});
