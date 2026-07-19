import { expect, test, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithConnection } from "../test/helpers";
import type { ApiClient } from "../lib/api/client";
import type { DubParams, TtsEngineInfo, TaskRecord } from "../lib/api/types";
import { DubbingStudioView } from "./DubbingStudioView";

vi.mock("@tauri-apps/api/core", () => ({
  convertFileSrc: (path: string) => `asset://localhost/${path}`,
}));

const ENGINES: TtsEngineInfo[] = [
  { id: "voxcpm2", kind: "local", voice_modes: ["clone", "design"], available: true },
  { id: "say_preview", kind: "local", voice_modes: ["preview"], available: true },
  { id: "cloud_placeholder", kind: "placeholder", voice_modes: [], available: false },
];

const PARAMS: DubParams = {
  engine_id: null,
  voice_mode: "clone",
  instruction: null,
  cfg: null,
  timesteps: null,
  seed: null,
  denoise: null,
  preview_voice: null,
  preview_rate: null,
  dub_text: "auto",
};

const TASK: TaskRecord = {
  schema_version: 1,
  id: "t1",
  project: "default",
  input_path: "/tmp/in.mp4",
  profile: "av-dub",
  name: "dub task",
  status: "paused",
  stages: [
    { type: "diarize", status: "completed", params: {}, pause_after: false, artifacts: ["speakers.json"], error: null },
    { type: "tts_synthesize", status: "completed", params: {}, pause_after: false, artifacts: ["dub-manifest.json"], error: null },
    { type: "align_duration", status: "completed", params: {}, pause_after: false, artifacts: [], error: null },
    { type: "mix_audio", status: "completed", params: {}, pause_after: false, artifacts: ["dub-mix.wav"], error: null },
    { type: "mux", status: "pending", params: {}, pause_after: false, artifacts: [], error: null },
  ],
  glossary: { global_ids: [], use_task: false, asr_mode: "auto" },
  created_at: "2026-07-20T00:00:00+00:00",
  updated_at: "2026-07-20T00:00:00+00:00",
};

function api(overrides: Partial<ApiClient> = {}) {
  return {
    showTask: vi.fn().mockResolvedValue(TASK),
    listDubEngines: vi.fn().mockResolvedValue({ engines: ENGINES }),
    getDubParams: vi.fn().mockResolvedValue(PARAMS),
    patchDubParams: vi.fn(async (_p: string, _t: string, params: Partial<DubParams>) => ({
      ...PARAMS,
      ...params,
    })),
    dubRedub: vi.fn().mockResolvedValue({ queued: true }),
    ...overrides,
  } as unknown as ApiClient;
}

function render(client = api()) {
  renderWithConnection(
    <DubbingStudioView project="default" taskId="t1" onBack={() => {}} />,
    { api: client },
  );
}

test("renders the engine menu with placeholder disabled", async () => {
  render();
  await screen.findByText("配音工作室");
  expect(await screen.findByRole("button", { name: /VoxCPM2/ })).toBeEnabled();
  expect(await screen.findByRole("button", { name: /macOS say/ })).toBeEnabled();
  const cloud = await screen.findByRole("button", { name: /雲端/ });
  expect(cloud).toBeDisabled();
  expect(cloud.textContent).toMatch(/即將推出/);
});

test("selecting say_preview switches the parameter area", async () => {
  render();
  await screen.findByText("配音工作室");
  // VoxCPM2 is the default selected engine; design instruction only for design mode.
  await userEvent.click(await screen.findByRole("button", { name: /macOS say/ }));
  expect(screen.getByText(/voice/i)).toBeInTheDocument();
});

test("apply and resynthesize writes params and triggers redub", async () => {
  const client = api();
  render(client);
  await screen.findByText("配音工作室");
  await userEvent.click(screen.getByRole("button", { name: /套用並重新合成/ }));
  await waitFor(() => expect(client.patchDubParams).toHaveBeenCalled());
  await waitFor(() => expect(client.dubRedub).toHaveBeenCalledWith("default", "t1", "synthesize"));
});

test("resynthesize from diarize triggers the diarize redub path", async () => {
  const client = api();
  render(client);
  await screen.findByText("配音工作室");
  await userEvent.click(screen.getByRole("button", { name: /從說話人分離重來/ }));
  await waitFor(() => expect(client.dubRedub).toHaveBeenCalledWith("default", "t1", "diarize"));
});
