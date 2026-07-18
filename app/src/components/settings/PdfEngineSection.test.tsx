import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ApiClient } from "../../lib/api/client";
import { renderWithConnection } from "../../test/helpers";
import { PdfEngineSection } from "./PdfEngineSection";

const notInstalled = {
  python: "python3.12",
  venv: false,
  installed: false,
  state: "idle" as const,
  installing: false,
  error: null,
  installed_mb: 0,
};

test("shows python and engine status, install enabled when missing", async () => {
  const api: Partial<ApiClient> = {
    getPdfEngineStatus: vi.fn().mockResolvedValue(notInstalled),
  };
  renderWithConnection(<PdfEngineSection pdf={{ python: "" }} onChange={() => {}} />, { api });
  await waitFor(() => expect(screen.getByText("未安裝")).toBeInTheDocument());
  expect(screen.getByText("python3.12")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "安裝引擎" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "測試" })).toBeDisabled();
});

test("no compatible python disables install", async () => {
  const api: Partial<ApiClient> = {
    getPdfEngineStatus: vi.fn().mockResolvedValue({ ...notInstalled, python: "" }),
  };
  renderWithConnection(<PdfEngineSection pdf={{ python: "" }} onChange={() => {}} />, { api });
  await screen.findByText(/找不到相容的 Python/);
  expect(screen.getByRole("button", { name: "安裝引擎" })).toBeDisabled();
});

test("install button starts the install", async () => {
  const installPdfEngine = vi.fn().mockResolvedValue({ installing: true });
  const api: Partial<ApiClient> = {
    getPdfEngineStatus: vi.fn().mockResolvedValue(notInstalled),
    installPdfEngine,
  };
  renderWithConnection(<PdfEngineSection pdf={{ python: "" }} onChange={() => {}} />, { api });
  await screen.findByText("未安裝");
  await userEvent.click(screen.getByRole("button", { name: "安裝引擎" }));
  await waitFor(() => expect(installPdfEngine).toHaveBeenCalled());
});

test("installed engine can be tested and shows version", async () => {
  const api: Partial<ApiClient> = {
    getPdfEngineStatus: vi.fn().mockResolvedValue({
      ...notInstalled,
      venv: true,
      installed: true,
      installed_mb: 800,
    }),
    testPdfEngine: vi.fn().mockResolvedValue({ ok: true, version: "2.9.0" }),
  };
  renderWithConnection(<PdfEngineSection pdf={{ python: "" }} onChange={() => {}} />, { api });
  await screen.findByText(/已安裝/);
  expect(screen.getByRole("button", { name: "安裝引擎" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "測試" }));
  await waitFor(() =>
    expect(screen.getByText(/測試通過（2\.9\.0）/)).toBeInTheDocument(),
  );
});

test("python override edits flow through and engine info shows", async () => {
  const onChange = vi.fn();
  const api: Partial<ApiClient> = {
    getPdfEngineStatus: vi.fn().mockResolvedValue({
      python: "python3.12",
      venv: false,
      installed: false,
      state: "idle",
      installing: false,
      warming: false,
      error: null,
      installed_mb: 0,
      cache_mb: 0,
    }),
  };
  const { fireEvent } = await import("@testing-library/react");
  renderWithConnection(
    <PdfEngineSection pdf={{ python: "" }} onChange={onChange} />,
    { api },
  );
  await screen.findByText(/pdf2zh-next（BabelDOC/);
  await screen.findByText(/1\.1 GB/);
  fireEvent.change(screen.getByLabelText("Python 直譯器"), {
    target: { value: "/opt/py/bin/python3.11" },
  });
  expect(onChange).toHaveBeenCalledWith({ python: "/opt/py/bin/python3.11" });
});

test("warming state shows asset download progress", async () => {
  const api: Partial<ApiClient> = {
    getPdfEngineStatus: vi.fn().mockResolvedValue({
      python: "python3.12",
      venv: true,
      installed: true,
      state: "warming",
      installing: false,
      warming: true,
      error: null,
      installed_mb: 1250,
      cache_mb: 120,
    }),
  };
  renderWithConnection(
    <PdfEngineSection pdf={{ python: "" }} onChange={() => {}} />,
    { api },
  );
  await screen.findByText(/預熱中（下載模型資產）（120 MB）/);
});
