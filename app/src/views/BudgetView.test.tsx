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
