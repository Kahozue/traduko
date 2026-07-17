import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ApiClient } from "../../lib/api/client";
import { renderWithConnection } from "../../test/helpers";
import { AsrSection } from "./AsrSection";

const notCached = {
  package: true,
  model: "small",
  cached: false,
  state: "idle" as const,
  downloading: false,
  downloaded_mb: 0,
  error: null,
};

test("shows engine and model status, download enabled when missing", async () => {
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue(notCached),
  };
  renderWithConnection(<AsrSection />, { api });
  await waitFor(() => expect(screen.getByText("未下載")).toBeInTheDocument());
  expect(screen.getByText("引擎已內建")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "下載模型" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "測試" })).toBeDisabled();
});

test("download button starts the download", async () => {
  const downloadAsrModel = vi.fn().mockResolvedValue({ downloading: true, model: "small" });
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue(notCached),
    downloadAsrModel,
  };
  renderWithConnection(<AsrSection />, { api });
  await screen.findByText("未下載");
  await userEvent.click(screen.getByRole("button", { name: "下載模型" }));
  await waitFor(() => expect(downloadAsrModel).toHaveBeenCalledWith("small"));
});

test("cached model can be tested", async () => {
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue({
      ...notCached,
      cached: true,
      downloaded_mb: 484,
    }),
    testAsr: vi.fn().mockResolvedValue({ ok: true, load_seconds: 1.2 }),
  };
  renderWithConnection(<AsrSection />, { api });
  await screen.findByText(/已下載/);
  expect(screen.getByRole("button", { name: "下載模型" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "測試" }));
  await waitFor(() => expect(screen.getByText(/測試通過/)).toBeInTheDocument());
});

test("engine missing disables download", async () => {
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue({ ...notCached, package: false }),
  };
  renderWithConnection(<AsrSection />, { api });
  await screen.findByText("引擎未安裝");
  expect(screen.getByRole("button", { name: "下載模型" })).toBeDisabled();
});
