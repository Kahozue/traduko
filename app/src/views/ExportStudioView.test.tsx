import { expect, test, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithConnection } from "../test/helpers";
import type { ApiClient } from "../lib/api/client";
import type { ExportEstimate, SubtitleStylePreset, TaskRecord } from "../lib/api/types";
import { ExportStudioView } from "./ExportStudioView";

vi.mock("@tauri-apps/api/core", () => ({
  convertFileSrc: (path: string) => `asset://localhost/${path}`,
}));

const STYLES: Record<string, SubtitleStylePreset> = {
  default: {
    font_name: "Noto Sans TC",
    font_size: 48,
    primary_color: "#ffffff",
    outline_color: "#000000",
    outline: 2,
    shadow: 0,
    bold: false,
    alignment: 2,
    margin_v: 40,
  },
};

const ESTIMATE: ExportEstimate = {
  size_bytes: 524_288_000,
  eta_seconds: 180,
  disk_ok: true,
  disk_available: 50_000_000_000,
  duration: 600,
  width: 1920,
  height: 1080,
};

function task(overrides: Partial<TaskRecord> = {}): TaskRecord {
  return {
    schema_version: 1,
    id: "t1",
    project: "default",
    input_path: "/tmp/in.mp4",
    profile: "av-dub",
    name: "video task",
    status: "completed",
    stages: [
      {
        type: "mix_audio",
        status: "completed",
        params: {},
        pause_after: false,
        artifacts: ["dub-mix.wav"],
        error: null,
      },
    ],
    glossary: { global_ids: [], use_task: false, asr_mode: "auto" },
    created_at: "2026-07-20T00:00:00+00:00",
    updated_at: "2026-07-20T00:00:00+00:00",
    ...overrides,
  };
}

function api(overrides: Record<string, unknown> = {}) {
  return {
    showTask: vi.fn().mockResolvedValue(task()),
    getStyles: vi.fn().mockResolvedValue(STYLES),
    estimateExport: vi.fn().mockResolvedValue(ESTIMATE),
    createExport: vi.fn().mockResolvedValue({ queued: true }),
    ...overrides,
  } as unknown as ApiClient;
}

function render(client = api()) {
  renderWithConnection(
    <ExportStudioView project="default" taskId="t1" onBack={() => {}} />,
    { api: client },
  );
}

test("a video task gets the video panel", async () => {
  render();
  await screen.findByText("匯出工作室");
  expect(await screen.findByLabelText("容器")).toBeInTheDocument();
  expect(screen.getByLabelText("解析度")).toBeInTheDocument();
  expect(screen.getByLabelText("品質（CRF）")).toBeInTheDocument();
  expect(screen.getByLabelText("字幕")).toBeInTheDocument();
  expect(screen.queryByLabelText("格式")).not.toBeInTheDocument();
});

test("an audio task gets the audio panel", async () => {
  render(api({ showTask: vi.fn().mockResolvedValue(task({ input_path: "/tmp/in.mp3" })) }));
  await screen.findByText("匯出工作室");
  expect(await screen.findByLabelText("格式")).toBeInTheDocument();
  expect(screen.getByLabelText("來源")).toBeInTheDocument();
  expect(screen.queryByLabelText("容器")).not.toBeInTheDocument();
});

test("estimate runs on load and again after a parameter change", async () => {
  const client = api();
  render(client);
  await screen.findByText("匯出工作室");
  await waitFor(() => expect(client.estimateExport).toHaveBeenCalled());
  const before = (client.estimateExport as ReturnType<typeof vi.fn>).mock.calls.length;
  await userEvent.selectOptions(await screen.findByLabelText("解析度"), "720p");
  await waitFor(() =>
    expect(
      (client.estimateExport as ReturnType<typeof vi.fn>).mock.calls.length,
    ).toBeGreaterThan(before),
  );
  const calls = (client.estimateExport as ReturnType<typeof vi.fn>).mock.calls;
  expect(calls[calls.length - 1][2]).toMatchObject({ width: 1280, height: 720 });
});

test("the estimate shows size and duration and the start button is enabled", async () => {
  render();
  await screen.findByText("匯出工作室");
  expect(await screen.findByTestId("export-estimate")).toHaveTextContent("500");
  expect(screen.getByRole("button", { name: "開始匯出" })).toBeEnabled();
});

test("insufficient disk space blocks the export", async () => {
  const client = api({
    estimateExport: vi.fn().mockResolvedValue({
      ...ESTIMATE,
      disk_ok: false,
      disk_available: 1_000_000,
    }),
  });
  render(client);
  await screen.findByText("匯出工作室");
  expect(await screen.findByText(/磁碟空間不足/)).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "開始匯出" })).toBeDisabled(),
  );
});

test("start export posts the panel parameters", async () => {
  const client = api();
  render(client);
  await screen.findByText("匯出工作室");
  await screen.findByTestId("export-estimate");
  await userEvent.click(screen.getByRole("button", { name: "開始匯出" }));
  await waitFor(() => expect(client.createExport).toHaveBeenCalled());
  const call = (client.createExport as ReturnType<typeof vi.fn>).mock.calls[0];
  expect(call[0]).toBe("default");
  expect(call[2]).toBe("video");
  expect(call[3]).toMatchObject({ container: "mp4", audio_track: "original" });
});

test("the subtitle overlay preview appears once subtitles are turned on", async () => {
  render();
  await screen.findByText("匯出工作室");
  expect(screen.queryByTestId("subtitle-overlay")).not.toBeInTheDocument();
  await userEvent.selectOptions(await screen.findByLabelText("字幕"), "target");
  expect(await screen.findByTestId("subtitle-overlay")).toBeInTheDocument();
});

test("the dubbed audio track is unavailable without a dub mix", async () => {
  const client = api({
    showTask: vi.fn().mockResolvedValue(
      task({
        stages: [
          {
            type: "translate",
            status: "completed",
            params: {},
            pause_after: false,
            artifacts: ["translation.json"],
            error: null,
          },
        ],
      }),
    ),
  });
  render(client);
  await screen.findByText("匯出工作室");
  const select = await screen.findByLabelText("音軌");
  expect(
    Array.from((select as HTMLSelectElement).options).find((o) => o.value === "dub"),
  ).toBeDisabled();
});

const COMPOSE_STAGES = [
  {
    type: "ingest_transcript",
    status: "completed" as const,
    params: {},
    pause_after: false,
    artifacts: ["01-segments.json"],
    error: null,
  },
  {
    type: "mix_audio",
    status: "completed" as const,
    params: {},
    pause_after: false,
    artifacts: ["dub-mix.wav"],
    error: null,
  },
  {
    type: "export_audio",
    status: "completed" as const,
    params: {},
    pause_after: false,
    artifacts: ["06-dubbed.m4a"],
    error: null,
  },
];

function composeTask() {
  return task({
    input_path: "/tmp/lines.srt",
    profile: "audio-compose",
    stages: COMPOSE_STAGES,
  });
}

test("a compose task lands in the audio panel despite its transcript input", async () => {
  render(api({ showTask: vi.fn().mockResolvedValue(composeTask()) }));
  await screen.findByText("匯出工作室");
  expect(await screen.findByLabelText("格式")).toBeInTheDocument();
  expect(screen.queryByLabelText("容器")).not.toBeInTheDocument();
});

test("a compose task cannot export the original audio it never had", async () => {
  render(api({ showTask: vi.fn().mockResolvedValue(composeTask()) }));
  await screen.findByText("匯出工作室");
  const sourceSelect = await screen.findByLabelText("來源");
  const original = within(sourceSelect).getByRole("option", { name: "原始音訊" });
  expect(original).toBeDisabled();
  expect(sourceSelect).toHaveValue("dub");
});

test("a compose task shows no source preview", async () => {
  render(api({ showTask: vi.fn().mockResolvedValue(composeTask()) }));
  await screen.findByText("匯出工作室");
  await screen.findByLabelText("格式");
  // Nothing to play: the input is a transcript, not a recording.
  expect(screen.queryByText("預覽")).toBeNull();
});
