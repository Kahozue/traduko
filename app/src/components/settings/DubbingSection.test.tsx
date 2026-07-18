import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ApiClient } from "../../lib/api/client";
import { renderWithConnection } from "../../test/helpers";
import { DubbingSection } from "./DubbingSection";

const notInstalled = {
  python: "python3.11",
  venv: false,
  installed: false,
  state: "idle" as const,
  installing: false,
  error: null,
  installed_mb: 0,
};

const dubbing = { hf_token: "", python: "" };

test("shows python and engine status, install enabled when missing", async () => {
  const api: Partial<ApiClient> = {
    getDubbingStatus: vi.fn().mockResolvedValue(notInstalled),
  };
  renderWithConnection(
    <DubbingSection dubbing={dubbing} onChange={() => {}} />,
    { api },
  );
  await waitFor(() => expect(screen.getByText("未安裝")).toBeInTheDocument());
  expect(screen.getByText("python3.11")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "安裝引擎" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "測試" })).toBeDisabled();
});

test("no compatible python disables install", async () => {
  const api: Partial<ApiClient> = {
    getDubbingStatus: vi.fn().mockResolvedValue({ ...notInstalled, python: "" }),
  };
  renderWithConnection(
    <DubbingSection dubbing={dubbing} onChange={() => {}} />,
    { api },
  );
  await screen.findByText(/找不到相容的 Python/);
  expect(screen.getByRole("button", { name: "安裝引擎" })).toBeDisabled();
});

test("install button starts the install", async () => {
  const installDubbingEngine = vi.fn().mockResolvedValue({ installing: true });
  const api: Partial<ApiClient> = {
    getDubbingStatus: vi.fn().mockResolvedValue(notInstalled),
    installDubbingEngine,
  };
  renderWithConnection(
    <DubbingSection dubbing={dubbing} onChange={() => {}} />,
    { api },
  );
  await screen.findByText("未安裝");
  await userEvent.click(screen.getByRole("button", { name: "安裝引擎" }));
  await waitFor(() => expect(installDubbingEngine).toHaveBeenCalled());
});

test("installed engine can be tested and shows torch and mps", async () => {
  const api: Partial<ApiClient> = {
    getDubbingStatus: vi.fn().mockResolvedValue({
      ...notInstalled,
      venv: true,
      installed: true,
      installed_mb: 4200,
    }),
    testDubbingEngine: vi
      .fn()
      .mockResolvedValue({ ok: true, torch: "2.5.0", mps: true }),
  };
  renderWithConnection(
    <DubbingSection dubbing={dubbing} onChange={() => {}} />,
    { api },
  );
  await screen.findByText(/已安裝/);
  expect(screen.getByRole("button", { name: "安裝引擎" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "測試" }));
  await waitFor(() =>
    expect(screen.getByText(/測試通過（torch 2\.5\.0 · MPS）/)).toBeInTheDocument(),
  );
});

test("hf token edits flow through onChange", async () => {
  const onChange = vi.fn();
  const api: Partial<ApiClient> = {
    getDubbingStatus: vi.fn().mockResolvedValue(notInstalled),
  };
  renderWithConnection(
    <DubbingSection dubbing={dubbing} onChange={onChange} />,
    { api },
  );
  await screen.findByText("未安裝");
  await userEvent.type(screen.getByLabelText("Hugging Face Token"), "h");
  expect(onChange).toHaveBeenCalledWith({ hf_token: "h", python: "" });
});
