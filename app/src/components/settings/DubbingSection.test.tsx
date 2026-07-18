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

const dubbing = { hf_token: "", python: "", inference_timesteps: null, cfg_value: null, seed: null, denoise: false };

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
    expect(
      screen.getByText(/測試通過（voxcpm — · torch 2\.5\.0 · MPS 加速）/),
    ).toBeInTheDocument(),
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
  expect(onChange).toHaveBeenCalledWith({ ...dubbing, hf_token: "h" });
});

test("model predownload row shows size and starts the download", async () => {
  const downloadDubbingModel = vi.fn().mockResolvedValue({ downloading: true });
  const api: Partial<ApiClient> = {
    getDubbingStatus: vi.fn().mockResolvedValue(notInstalled),
    getDubbingModelStatus: vi.fn().mockResolvedValue({
      repo: "openbmb/VoxCPM2",
      total_mb: 4960,
      downloaded_mb: 0,
      cached: false,
      state: "idle",
      downloading: false,
      error: null,
    }),
    downloadDubbingModel,
  };
  renderWithConnection(<DubbingSection dubbing={dubbing} onChange={() => {}} />, { api });
  await screen.findByText(/VoxCPM2（4\.96 GB/);
  await userEvent.click(screen.getByRole("button", { name: "預先下載" }));
  await waitFor(() => expect(downloadDubbingModel).toHaveBeenCalled());
});

test("synthesis defaults write numbers or null into the draft", async () => {
  const { fireEvent } = await import("@testing-library/react");
  const onChange = vi.fn();
  const api: Partial<ApiClient> = {
    getDubbingStatus: vi.fn().mockResolvedValue(notInstalled),
  };
  renderWithConnection(<DubbingSection dubbing={dubbing} onChange={onChange} />, { api });
  fireEvent.change(screen.getByLabelText("推理步數"), { target: { value: "24" } });
  expect(onChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ inference_timesteps: 24 }),
  );
  await userEvent.click(screen.getByLabelText("參考音降噪"));
  expect(onChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ denoise: true }),
  );
});

test("invalid python override warns with the resolved fallback", async () => {
  const api: Partial<ApiClient> = {
    getDubbingStatus: vi.fn().mockResolvedValue({
      ...notInstalled,
      python: "python3.11",
    }),
  };
  renderWithConnection(
    <DubbingSection
      dubbing={{ ...dubbing, python: "/opt/nonexistent/python" }}
      onChange={() => {}}
    />,
    { api },
  );
  await screen.findByText(/指定的直譯器無效/);
});
