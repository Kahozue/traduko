import { expect, test, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithConnection } from "../test/helpers";
import type { ApiClient } from "../lib/api/client";
import type {
  ArtifactListItem,
  DubManifestDoc,
  DubParams,
  SayVoice,
  SpeakersDoc,
  TtsEngineInfo,
  TaskRecord,
} from "../lib/api/types";
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

// Stage artifacts carry the writer's index prefix on disk (02-speakers.json),
// exactly as the core records them; anything comparing bare names must go
// through the artifacts listing, whose `name` field strips the prefix.
const TASK: TaskRecord = {
  schema_version: 1,
  id: "t1",
  project: "default",
  input_path: "/tmp/in.mp4",
  profile: "av-dub",
  name: "dub task",
  status: "paused",
  stages: [
    { type: "diarize", status: "completed", params: {}, pause_after: false, artifacts: ["02-speakers.json"], error: null },
    { type: "tts_synthesize", status: "completed", params: {}, pause_after: false, artifacts: ["03-dub-manifest.json"], error: null },
    { type: "align_duration", status: "completed", params: {}, pause_after: false, artifacts: ["04-dub-timeline.json"], error: null },
    { type: "mix_audio", status: "completed", params: {}, pause_after: false, artifacts: ["05-dub-mix.wav"], error: null },
    { type: "mux", status: "pending", params: {}, pause_after: false, artifacts: [], error: null },
  ],
  glossary: { global_ids: [], use_task: false, asr_mode: "auto" },
  created_at: "2026-07-20T00:00:00+00:00",
  updated_at: "2026-07-20T00:00:00+00:00",
};

const ARTIFACTS: ArtifactListItem[] = [
  { file: "01-translation.json", index: 1, name: "translation.json", schema_version: 1, size: 500, mtime: 0 },
  { file: "02-speakers.json", index: 2, name: "speakers.json", schema_version: 1, size: 200, mtime: 1 },
  { file: "03-dub-manifest.json", index: 3, name: "dub-manifest.json", schema_version: 1, size: 400, mtime: 2 },
  { file: "03-ref-S1.wav", index: 3, name: "ref-S1.wav", schema_version: null, size: 1200, mtime: 2 },
  { file: "03-ref-S2.wav", index: 3, name: "ref-S2.wav", schema_version: null, size: 1300, mtime: 2 },
  { file: "04-dub-timeline.json", index: 4, name: "dub-timeline.json", schema_version: 1, size: 300, mtime: 3 },
  { file: "05-dub-mix.wav", index: 5, name: "dub-mix.wav", schema_version: null, size: 9000, mtime: 4 },
];

const SPEAKERS: SpeakersDoc = {
  schema_version: 1,
  speakers: [
    { id: "S1", label: "Speaker 1", ref_start: 1.0, ref_end: 5.0, ref_text: "早安" },
    { id: "S2", label: "Speaker 2", ref_start: 9.0, ref_end: 12.0, ref_text: "午安" },
  ],
  segments: [
    { id: 1, speaker: "S1" },
    { id: 2, speaker: "S2" },
  ],
};

const MANIFEST: DubManifestDoc = {
  schema_version: 1,
  segments: [
    { id: 1, speaker: "S1", file: "03-dub/seg-1.wav", duration: 1.4, status: "synthesized", error: "" },
    { id: 2, speaker: "S2", file: "", duration: 0, status: "failed", error: "empty dub text" },
  ],
};

const TIMELINE = {
  schema_version: 1,
  mode: "timed",
  note: "",
  segments: [
    { id: 1, start: 61.5, window: 2.0, duration: 1.4, tempo: 1.0, regenerated: false, file: "03-dub/seg-1.wav", status: "fit" },
    { id: 2, start: 70.0, window: 2.0, duration: 0.0, tempo: 1.0, regenerated: false, file: "", status: "failed" },
  ],
};

const TRANSLATION = {
  segments: [
    { id: 1, start: 61.5, end: 63.5, source: "good morning", target: "早安" },
    { id: 2, start: 70.0, end: 72.0, source: "good afternoon", target: "午安" },
  ],
};

const VOICES: SayVoice[] = [
  { name: "Meijia", locale: "zh_TW" },
  { name: "Alex", locale: "en_US" },
];

function readArtifactFake() {
  return vi.fn(async (_p: string, _t: string, name: string) => {
    if (name === "speakers.json") return SPEAKERS;
    if (name === "dub-manifest.json") return MANIFEST;
    if (name === "dub-timeline.json") return TIMELINE;
    if (name === "translation.json") return TRANSLATION;
    throw new Error(`no artifact ${name}`);
  });
}

function api(overrides: Partial<ApiClient> = {}) {
  return {
    showTask: vi.fn().mockResolvedValue(TASK),
    listArtifacts: vi.fn().mockResolvedValue(ARTIFACTS),
    listDubEngines: vi.fn().mockResolvedValue({ engines: ENGINES }),
    getDubParams: vi.fn().mockResolvedValue(PARAMS),
    patchDubParams: vi.fn(async (_p: string, _t: string, params: Partial<DubParams>) => ({
      ...PARAMS,
      ...params,
    })),
    dubRedub: vi.fn().mockResolvedValue({ queued: true }),
    listDubVoices: vi.fn().mockResolvedValue({ voices: VOICES }),
    readArtifact: readArtifactFake(),
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
  expect(screen.getByLabelText("語音")).toBeInTheDocument();
  expect(screen.getByLabelText("語速")).toBeInTheDocument();
});

test("apply and resynthesize writes params and triggers redub", async () => {
  const client = api();
  render(client);
  await screen.findByText("配音工作室");
  await userEvent.click(screen.getByRole("button", { name: /套用並重新合成/ }));
  await waitFor(() => expect(client.patchDubParams).toHaveBeenCalled());
  await waitFor(() => expect(client.dubRedub).toHaveBeenCalledWith("default", "t1", "synthesize"));
});

test("resynthesize from diarize confirms before triggering the redub", async () => {
  // Both the footer button and the empty-state "separate now" run the same
  // destructive redub("diarize"); both must route through one confirmation.
  const client = api();
  render(client);
  await screen.findByText("配音工作室");
  await userEvent.click(await screen.findByRole("button", { name: /從說話人分離重來/ }));
  expect(client.dubRedub).not.toHaveBeenCalled();
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "立即分離" }));
  await waitFor(() => expect(client.dubRedub).toHaveBeenCalledWith("default", "t1", "diarize"));
});

// Guard for H1: with the real prefixed artifact shape, the speaker and
// preview sections must still detect their artifacts instead of falling
// into the empty states.
test("prefixed stage artifacts still detect speakers and the dub mix", async () => {
  render();
  await screen.findByText("配音工作室");
  await waitFor(() => expect(screen.queryByText("尚未分離說話人")).toBeNull());
  expect(screen.queryByText("尚未合成片段")).toBeNull();
  const mix = await waitFor(() => {
    const el = [...document.querySelectorAll("audio")].find((node) =>
      node.getAttribute("src")?.includes("dub-mix.wav"),
    );
    expect(el).toBeDefined();
    return el!;
  });
  expect(mix.getAttribute("src")).toContain("05-dub-mix.wav");
});

test("missing artifacts render the speaker and preview empty states", async () => {
  render(api({ listArtifacts: vi.fn().mockResolvedValue([]) }));
  await screen.findByText("配音工作室");
  expect(await screen.findByText("尚未分離說話人")).toBeInTheDocument();
  expect(await screen.findByText("尚未合成片段")).toBeInTheDocument();
});

// --- M7: the studio's missing half (v3_5-11 Task 6) -------------------------

test("the speaker section lists speakers with their reference audio", async () => {
  render();
  await screen.findByText("配音工作室");
  const section = await screen.findByRole("group", { name: "說話人" });
  expect(await within(section).findByText("Speaker 1")).toBeInTheDocument();
  expect(within(section).getByText("Speaker 2")).toBeInTheDocument();
  expect(within(section).getByText(/早安/)).toBeInTheDocument();
  // Reference clips play from their real prefixed filenames.
  const players = section.querySelectorAll("audio");
  expect(players.length).toBe(2);
  expect(players[0].getAttribute("src")).toContain("03-ref-S1.wav");
});

test("without speakers the section offers to separate them now", async () => {
  const client = api({
    listArtifacts: vi.fn().mockResolvedValue([]),
    readArtifact: vi.fn().mockRejectedValue(new Error("missing")),
  });
  render(client);
  await screen.findByText("配音工作室");
  const separate = await screen.findByRole("button", { name: "立即分離" });
  await userEvent.click(separate);
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "立即分離" }));
  await waitFor(() =>
    expect(client.dubRedub).toHaveBeenCalledWith("default", "t1", "diarize"),
  );
});

test("the preview section lists each segment with its timecode and text", async () => {
  render();
  await screen.findByText("配音工作室");
  const rows = await screen.findAllByTestId("dub-segment");
  expect(rows.length).toBe(2);
  expect(rows[0]).toHaveTextContent("01:01");
  expect(rows[0]).toHaveTextContent("早安");
  expect(rows[0].querySelector("audio")?.getAttribute("src")).toContain("03-dub/seg-1.wav");
  // A failed segment says so instead of offering a player.
  expect(rows[1]).toHaveTextContent(/失敗|empty dub text/);
  expect(rows[1].querySelector("audio")).toBeNull();
});

test("a manifest without a mix still renders the segment list", async () => {
  // Regression: both branches were false, so the section rendered blank.
  const client = api({
    listArtifacts: vi.fn().mockResolvedValue(
      ARTIFACTS.filter((item) => item.name !== "dub-mix.wav"),
    ),
  });
  render(client);
  await screen.findByText("配音工作室");
  expect((await screen.findAllByTestId("dub-segment")).length).toBe(2);
  expect(screen.queryByText("尚未合成片段")).toBeNull();
});

test("the say engine offers system voices from the core", async () => {
  render();
  await screen.findByText("配音工作室");
  await userEvent.click(await screen.findByRole("button", { name: /macOS say/ }));
  const select = await screen.findByLabelText("語音");
  expect(within(select).getByRole("option", { name: /Meijia/ })).toBeInTheDocument();
  expect(within(select).getByRole("option", { name: /Alex/ })).toBeInTheDocument();
});

test("picking the say engine locks the voice mode to preview", async () => {
  const client = api();
  render(client);
  await screen.findByText("配音工作室");
  await userEvent.click(await screen.findByRole("button", { name: /macOS say/ }));
  await userEvent.click(screen.getByRole("button", { name: /套用並重新合成/ }));
  await waitFor(() => expect(client.patchDubParams).toHaveBeenCalled());
  const body = (client.patchDubParams as ReturnType<typeof vi.fn>).mock.calls[0][2];
  expect(body).toMatchObject({ engine_id: "say_preview", voice_mode: "preview" });
});

test("picking the preview voice mode selects the say engine", async () => {
  render();
  await screen.findByText("配音工作室");
  await userEvent.selectOptions(await screen.findByLabelText("聲音模式"), "preview");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /macOS say/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    ),
  );
});

test("voxcpm2 advanced parameters post only what was filled in", async () => {
  const client = api();
  render(client);
  await screen.findByText("配音工作室");
  await userEvent.click(await screen.findByText("進階參數"));
  await userEvent.type(screen.getByLabelText("種子"), "42");
  await userEvent.click(screen.getByRole("button", { name: /套用並重新合成/ }));
  await waitFor(() => expect(client.patchDubParams).toHaveBeenCalled());
  const body = (client.patchDubParams as ReturnType<typeof vi.fn>).mock.calls[0][2];
  expect(body.seed).toBe(42);
  // Blank fields follow the global defaults rather than pinning a value.
  expect(body.cfg).toBeUndefined();
  expect(body.timesteps).toBeUndefined();
});

test("a task without a diarize stage drops the separation controls", async () => {
  // Speaker separation is optional: the synthesis stage falls back to one
  // voice, so nothing here should read as a missing prerequisite.
  const noDiarize = {
    ...TASK,
    stages: TASK.stages.filter((stage) => stage.type !== "diarize"),
  };
  render(
    api({
      showTask: vi.fn().mockResolvedValue(noDiarize),
      listArtifacts: vi
        .fn()
        .mockResolvedValue(ARTIFACTS.filter((item) => item.name !== "speakers.json")),
    }),
  );
  await screen.findByText("配音工作室");
  expect(await screen.findByText("未做說話人分離，將以單一聲音配音")).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: /從說話人分離重來/ })).toBeNull(),
  );
  expect(screen.queryByRole("button", { name: /立即分離/ })).toBeNull();
  expect(screen.queryByText("尚未分離說話人")).toBeNull();
});

test("a skipped diarize stage still offers to separate now", async () => {
  const skipped = {
    ...TASK,
    stages: TASK.stages.map((stage) =>
      stage.type === "diarize" ? { ...stage, status: "skipped" as const } : stage,
    ),
  };
  render(
    api({
      showTask: vi.fn().mockResolvedValue(skipped),
      listArtifacts: vi
        .fn()
        .mockResolvedValue(ARTIFACTS.filter((item) => item.name !== "speakers.json")),
    }),
  );
  expect(await screen.findByText("未做說話人分離，將以單一聲音配音")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /立即分離/ })).toBeEnabled();
});
