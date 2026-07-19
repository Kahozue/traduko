import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

const openMock = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: (...args: unknown[]) => openMock(...args),
}));

import type { ApiClient } from "../lib/api/client";
import type { ProfileInfo } from "../lib/api/types";
import { renderWithConnection } from "../test/helpers";
import { CreateTaskDialog } from "./CreateTaskDialog";

const DETAILED: ProfileInfo[] = [
  { name: "av-default", kind: "video", stages: ["extract_audio", "asr", "translate"] },
  { name: "subtitle-translate", kind: "video", stages: ["ingest_subtitle", "translate"] },
  { name: "novel-translate", kind: "document", stages: ["ingest_document", "translate_chunks"] },
];

test("initialKind hides the type row and titles by domain", async () => {
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue([
      { name: "audio-transcribe", kind: "audio", stages: ["extract_audio", "asr"] },
    ]),
  };
  renderWithConnection(
    <CreateTaskDialog initialKind="audio" onClose={() => {}} onCreated={() => {}} />,
    { api },
  );
  expect(await screen.findByText("新增音頻任務")).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "任務類型" })).toBeNull();
  expect(screen.queryByRole("button", { name: /影片/ })).toBeNull();
});

test("without initialKind the type row shows and the title is generic", async () => {
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
  };
  renderWithConnection(
    <CreateTaskDialog onClose={() => {}} onCreated={() => {}} />,
    { api },
  );
  expect(await screen.findByText("新增任務")).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "任務類型" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /影片/ })).toBeInTheDocument();
});

test("picks file, selects a video profile and submits", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t-new", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    createTask,
  };
  const onCreated = vi.fn();
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={onCreated} />, { api });

  // Video is auto-selected (first kind with profiles); its two profiles show
  // in the combobox.
  await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.srt")).toBeInTheDocument());
  await userEvent.selectOptions(screen.getByRole("combobox"), "subtitle-translate");
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith({
      input_path: "/tmp/in.srt",
      profile: "subtitle-translate",
      project: "default",
    }),
  );
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("default", "t-new"));
});

test("choosing the document type switches to its single profile", async () => {
  openMock.mockResolvedValue("/tmp/novel.md");
  const createTask = vi.fn().mockResolvedValue({ id: "d1", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByRole("button", { name: /文檔/ })).toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: /文檔/ }));
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/novel.md")).toBeInTheDocument());
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({ profile: "novel-translate" }),
    ),
  );
});

test("a task type with no profiles is disabled", async () => {
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });
  await waitFor(() => expect(screen.getByRole("button", { name: /漫畫/ })).toBeDisabled());
});

test("file picker filter name follows the task type", async () => {
  openMock.mockResolvedValue("/tmp/novel.md");
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  // Video is auto-selected first: its filter keeps the subtitle/media name.
  await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() =>
    expect(openMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        filters: [expect.objectContaining({ name: "字幕或影音檔" })],
      }),
    ),
  );

  await userEvent.click(screen.getByRole("button", { name: /文檔/ }));
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() =>
    expect(openMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        filters: [expect.objectContaining({ name: "文件檔" })],
      }),
    ),
  );
});

test("close button calls onClose", async () => {
  const api: Partial<ApiClient> = { profilesDetailed: vi.fn().mockResolvedValue([]) };
  const onClose = vi.fn();
  renderWithConnection(<CreateTaskDialog onClose={onClose} onCreated={() => {}} />, { api });
  await userEvent.click(screen.getByText("取消"));
  expect(onClose).toHaveBeenCalled();
});

test("submits custom task name when provided", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t9", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.srt")).toBeInTheDocument());
  await userEvent.type(screen.getByLabelText("任務名稱"), "第三集");
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(expect.objectContaining({ name: "第三集" })),
  );
});

test("provider and model overrides are sent when chosen", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t2", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    getConfig: vi.fn().mockResolvedValue({
      default_provider: "glm",
      llm_providers: {
        glm: { type: "openai_compat", model: "glm-4" },
        deepseek: { type: "openai_compat", model: "deepseek-chat" },
      },
    }),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByLabelText("供應商")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.srt")).toBeInTheDocument());
  await userEvent.selectOptions(screen.getByLabelText("供應商"), "deepseek");
  await userEvent.type(screen.getByLabelText("模型"), "deepseek-reasoner");
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({ provider: "deepseek", model: "deepseek-reasoner" }),
    ),
  );
});

test("auto provider sends no override fields", async () => {
  openMock.mockResolvedValue("/tmp/in.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "t3", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(DETAILED),
    getConfig: vi.fn().mockResolvedValue({
      default_provider: "glm",
      llm_providers: { glm: { type: "openai_compat", model: "glm-4" } },
    }),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByLabelText("供應商")).toBeInTheDocument());
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.srt")).toBeInTheDocument());
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() => expect(createTask).toHaveBeenCalled());
  const body = createTask.mock.calls[0][0] as Record<string, unknown>;
  expect(body.provider).toBeUndefined();
  expect(body.model).toBeUndefined();
});

test("audio kind offers profiles and a per-task ASR engine", async () => {
  openMock.mockResolvedValue("/tmp/talk.mp3");
  const createTask = vi.fn().mockResolvedValue({ id: "a1", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue([
      ...DETAILED,
      { name: "audio-transcribe", kind: "audio", stages: ["extract_audio", "asr"] },
    ]),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByRole("button", { name: /音頻/ })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: /音頻/ }));
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/talk.mp3")).toBeInTheDocument());
  await userEvent.selectOptions(
    screen.getByLabelText("語音辨識引擎"),
    "openai_gpt4o",
  );
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        profile: "audio-transcribe",
        asr_engine: "openai_gpt4o",
      }),
    ),
  );
});

test("dub profile offers the voice mode; design carries the instruction", async () => {
  openMock.mockResolvedValue("/tmp/in.mp4");
  const createTask = vi.fn().mockResolvedValue({ id: "d9", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue([
      ...DETAILED,
      {
        name: "av-dub",
        kind: "video",
        stages: ["extract_audio", "asr", "translate", "diarize", "tts_synthesize"],
      },
    ]),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByLabelText("管線設定檔")).toBeInTheDocument());
  // Non-dub profiles show no voice mode field.
  expect(screen.queryByLabelText("聲音模式")).toBeNull();
  await userEvent.selectOptions(screen.getByLabelText("管線設定檔"), "av-dub");
  await userEvent.selectOptions(screen.getByLabelText("聲音模式"), "design");
  await userEvent.type(screen.getByLabelText("聲音描述"), "沉穩的年輕男聲");
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.mp4")).toBeInTheDocument());
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        profile: "av-dub",
        voice_mode: "design",
        voice_instruction: "沉穩的年輕男聲",
      }),
    ),
  );
});

test("preview voice mode shows its note and skips the instruction", async () => {
  openMock.mockResolvedValue("/tmp/in.mp4");
  const createTask = vi.fn().mockResolvedValue({ id: "d10", project: "default" });
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue([
      {
        name: "av-dub",
        kind: "video",
        stages: ["diarize", "tts_synthesize", "align_duration"],
      },
    ]),
    createTask,
  };
  renderWithConnection(<CreateTaskDialog onClose={() => {}} onCreated={() => {}} />, { api });

  await waitFor(() => expect(screen.getByLabelText("聲音模式")).toBeInTheDocument());
  await userEvent.selectOptions(screen.getByLabelText("聲音模式"), "preview");
  expect(screen.getByText(/macOS 系統語音/)).toBeInTheDocument();
  expect(screen.queryByLabelText("聲音描述")).toBeNull();
  await userEvent.click(screen.getByText("選擇檔案"));
  await waitFor(() => expect(screen.getByDisplayValue("/tmp/in.mp4")).toBeInTheDocument());
  await userEvent.click(screen.getByText("建立"));
  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({ voice_mode: "preview" }),
    ),
  );
  const body = createTask.mock.calls[0][0];
  expect(body.voice_instruction).toBeUndefined();
});

const AUDIO_PROFILES: ProfileInfo[] = [
  {
    name: "audio-dub",
    kind: "audio",
    stages: ["extract_audio", "asr", "tts_synthesize", "export_audio"],
  },
  {
    name: "audio-transcribe",
    kind: "audio",
    stages: ["extract_audio", "asr", "export_transcript"],
  },
];

function configWithAudio(dubEnabled: boolean) {
  return {
    schema_version: 1,
    default_project: "default",
    default_provider: "",
    llm_providers: {},
    audio: {
      diarize_enabled: true,
      dub_enabled: dubEnabled,
      translate_enabled: true,
    },
  };
}

test("audio kind defaults to a non-dub profile when dubbing is off globally", async () => {
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(AUDIO_PROFILES),
    getConfig: vi.fn().mockResolvedValue(configWithAudio(false)),
  };
  renderWithConnection(
    <CreateTaskDialog initialKind="audio" onClose={() => {}} onCreated={() => {}} />,
    { api },
  );
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "管線設定檔" })).toHaveValue(
      "audio-transcribe",
    ),
  );
});

test("audio kind defaults to the dub profile when dubbing is on globally", async () => {
  const api: Partial<ApiClient> = {
    profilesDetailed: vi.fn().mockResolvedValue(AUDIO_PROFILES),
    getConfig: vi.fn().mockResolvedValue(configWithAudio(true)),
  };
  renderWithConnection(
    <CreateTaskDialog initialKind="audio" onClose={() => {}} onCreated={() => {}} />,
    { api },
  );
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "管線設定檔" })).toHaveValue(
      "audio-dub",
    ),
  );
});
