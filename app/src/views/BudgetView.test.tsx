import { screen, waitFor } from "@testing-library/react";
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

test("charts spend by model with a donut, legend and ranking bars", async () => {
  const api: Partial<ApiClient> = {
    budget: vi.fn().mockResolvedValue({
      month_usd: 3,
      task_usd_limit: null,
      monthly_usd_limit: null,
      tasks: [],
      models: [
        { model: "gpt-4o", usd: 6 },
        { model: "whisper-1", usd: 4 },
      ],
    }),
  };
  renderWithConnection(<BudgetView />, { api });
  // Each model appears twice: once in the donut legend, once as a ranking bar.
  await waitFor(() => expect(screen.getAllByText("gpt-4o")).toHaveLength(2));
  expect(screen.getAllByText("whisper-1")).toHaveLength(2);
  expect(screen.getByText("60%")).toBeInTheDocument();
  expect(screen.getByText("40%")).toBeInTheDocument();
  // Donut centre shows the combined total.
  expect(screen.getByText("$10.00")).toBeInTheDocument();
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
