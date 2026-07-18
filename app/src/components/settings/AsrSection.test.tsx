import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ApiClient } from "../../lib/api/client";
import type { AsrConfigDoc } from "../../lib/api/types";
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

const ASR: AsrConfigDoc = {
  engine: "faster_whisper",
  audio_engine: "",
  model: "small",
  macos_locale: "",
  cloud_base_url: "https://api.openai.com/v1",
  cloud_api_key: "",
  cloud_api_key_env: "",
  custom_base_url: "",
  custom_api_key: "",
  custom_api_key_env: "",
  custom_model: "",
  zh_prompt: true,
};

function renderSection(
  api: Partial<ApiClient>,
  asr: AsrConfigDoc = ASR,
  onChange: (value: AsrConfigDoc) => void = () => {},
  domain?: "video" | "audio",
) {
  return renderWithConnection(
    <AsrSection asr={asr} onChange={onChange} domain={domain} />,
    { api },
  );
}

test("faster-whisper: shows engine and model status, download enabled when missing", async () => {
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue(notCached),
  };
  renderSection(api);
  await waitFor(() => expect(screen.getByText("未下載")).toBeInTheDocument());
  expect(screen.getByText("引擎已內建")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "下載模型" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "測試" })).toBeDisabled();
});

test("faster-whisper: download button starts the download", async () => {
  const downloadAsrModel = vi.fn().mockResolvedValue({ downloading: true, model: "small" });
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue(notCached),
    downloadAsrModel,
  };
  renderSection(api);
  await screen.findByText("未下載");
  await userEvent.click(screen.getByRole("button", { name: "下載模型" }));
  await waitFor(() => expect(downloadAsrModel).toHaveBeenCalledWith("small"));
});

test("faster-whisper: cached model can be tested", async () => {
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue({
      ...notCached,
      cached: true,
      downloaded_mb: 484,
    }),
    testAsr: vi.fn().mockResolvedValue({ ok: true, load_seconds: 1.2 }),
  };
  renderSection(api);
  await screen.findByText(/已下載/);
  expect(screen.getByRole("button", { name: "下載模型" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "測試" }));
  await waitFor(() => expect(screen.getByText(/測試通過/)).toBeInTheDocument());
});

test("faster-whisper: engine missing disables download", async () => {
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue({ ...notCached, package: false }),
  };
  renderSection(api);
  await screen.findByText("引擎未安裝");
  expect(screen.getByRole("button", { name: "下載模型" })).toBeDisabled();
});

test("engine select writes the domain default and gpt-4o warns about timestamps", async () => {
  const onChange = vi.fn();
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue(notCached),
  };
  const { unmount } = renderSection(api, ASR, onChange);
  await userEvent.selectOptions(screen.getByLabelText("引擎"), "openai_gpt4o");
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ engine: "openai_gpt4o" }),
  );
  unmount();
  // Re-render with the engine applied: warning note + key fields show.
  renderSection(api, { ...ASR, engine: "openai_gpt4o" });
  expect(screen.getByText(/不含時間戳/)).toBeInTheDocument();
  expect(screen.getByLabelText("API key")).toBeInTheDocument();
});

test("audio domain edits audio_engine and falls back to the video default", async () => {
  const onChange = vi.fn();
  const api: Partial<ApiClient> = {
    getAsrStatus: vi.fn().mockResolvedValue(notCached),
  };
  renderSection(api, { ...ASR, engine: "faster_whisper" }, onChange, "audio");
  const select = screen.getByLabelText("引擎") as HTMLSelectElement;
  // audio_engine empty: the menu mirrors the video default.
  expect(select.value).toBe("faster_whisper");
  await userEvent.selectOptions(select, "openai_gpt4o");
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ audio_engine: "openai_gpt4o", engine: "faster_whisper" }),
  );
});

test("macos engine probes locales and downloads assets", async () => {
  const getAsrEngines = vi.fn().mockResolvedValue({
    engines: [],
    macos: {
      platform_ok: true,
      available: true,
      probed: true,
      transcriber_locales: ["zh-TW", "ja-JP"],
      dictation_locales: ["zh-TW", "ja-JP", "th-TH"],
      installed_locales: ["zh-TW"],
      assets_state: "idle",
      assets_progress: 0,
      assets_error: null,
      error: null,
    },
    cloud_key_present: false,
    custom_ready: false,
  });
  const downloadMacosAssets = vi
    .fn()
    .mockResolvedValue({ downloading: true, locale: "ja-JP" });
  const api: Partial<ApiClient> = { getAsrEngines, downloadMacosAssets };
  renderSection(api, { ...ASR, engine: "macos_native", macos_locale: "ja-JP" });
  await waitFor(() => expect(getAsrEngines).toHaveBeenCalledWith(true));
  await screen.findByText(/此機器支援/);
  await userEvent.click(screen.getByRole("button", { name: "下載模型" }));
  await waitFor(() => expect(downloadMacosAssets).toHaveBeenCalledWith("ja-JP"));
});

test("custom endpoint engine exposes base url and model fields", async () => {
  const api: Partial<ApiClient> = {};
  renderSection(api, { ...ASR, engine: "cloud_custom" });
  expect(screen.getByLabelText("API 位址（base_url）")).toBeInTheDocument();
  expect(screen.getByLabelText("模型名稱")).toBeInTheDocument();
});

test("cloud connection test surfaces the result", async () => {
  const testAsrEngine = vi.fn().mockResolvedValue({ ok: false, error: "no API key configured" });
  const api: Partial<ApiClient> = { testAsrEngine };
  renderSection(api, { ...ASR, engine: "openai_whisper" });
  await userEvent.click(screen.getByRole("button", { name: "測試" }));
  await waitFor(() =>
    expect(testAsrEngine).toHaveBeenCalledWith({
      engine: "openai_whisper",
      model: "small",
      locale: "",
    }),
  );
  await screen.findByText("no API key configured");
});
