import { expect, test, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithConnection } from "../test/helpers";
import type { ApiClient } from "../lib/api/client";
import type { GlossaryTable, TaskRecord } from "../lib/api/types";
import { TaskGlossaryView } from "./TaskGlossaryView";

function stageOf(type: string) {
  return {
    type,
    status: "completed" as const,
    params: {},
    pause_after: false,
    artifacts: [],
    error: null,
  };
}

function table(overrides: Partial<GlossaryTable> = {}): GlossaryTable {
  return {
    id: "anime-terms",
    name: "動畫名詞",
    domain: "video",
    enabled: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    entry_count: 3,
    ...overrides,
  };
}

const TABLES: GlossaryTable[] = [
  table(),
  table({ id: "audio-terms", name: "廣播用語", domain: "audio" }),
  table({ id: "doc-terms", name: "論文術語", domain: "document" }),
  table({ id: "shared", name: "通用詞", domain: "general" }),
];

function task(overrides: Partial<TaskRecord> = {}): TaskRecord {
  return {
    schema_version: 1,
    id: "t1",
    project: "default",
    input_path: "/tmp/in.mp4",
    profile: "av-default",
    name: "video task",
    status: "completed",
    stages: [stageOf("extract_audio"), stageOf("asr"), stageOf("translate")],
    glossary: { global_ids: ["anime-terms"], use_task: false, asr_mode: "auto" },
    created_at: "2026-07-20T00:00:00+00:00",
    updated_at: "2026-07-20T00:00:00+00:00",
    ...overrides,
  };
}

function api(overrides: Record<string, unknown> = {}) {
  return {
    showTask: vi.fn().mockResolvedValue(task()),
    listGlossaries: vi.fn().mockResolvedValue(TABLES),
    getTaskGlossaryEntries: vi.fn().mockResolvedValue({
      entries: [
        { source: "Kirito", target: "桐人", notes: "", category: "人名" },
        { source: "Aincrad", target: "艾恩葛朗特", notes: "", category: "地名" },
      ],
    }),
    setTaskGlossary: vi.fn().mockResolvedValue(task()),
    putTaskGlossaryEntries: vi.fn().mockResolvedValue({ written: 2 }),
    reapplyGlossary: vi.fn().mockResolvedValue({ queued: true }),
    ...overrides,
  } as unknown as ApiClient;
}

function render(client = api()) {
  renderWithConnection(
    <TaskGlossaryView project="default" taskId="t1" onBack={() => {}} />,
    { api: client },
  );
  return client;
}

test("domain groups are localized, not half-English", async () => {
  render();
  expect(await screen.findByText("影片")).toBeInTheDocument();
  expect(screen.getByText("通用")).toBeInTheDocument();
  expect(screen.queryByText(/任務 - Video/)).toBeNull();
});

test("only this task's domain and the general tables are listed", async () => {
  // spec 3-(4): a video task has no business picking document tables.
  render();
  expect(await screen.findByText("動畫名詞")).toBeInTheDocument();
  expect(screen.getByText("通用詞")).toBeInTheDocument();
  expect(screen.queryByText("論文術語")).toBeNull();
  expect(screen.queryByText("廣播用語")).toBeNull();
});

test("a document task lists document and general tables", async () => {
  render(
    api({
      showTask: vi.fn().mockResolvedValue(
        task({
          profile: "novel-translate",
          input_path: "/tmp/in.txt",
          stages: [stageOf("ingest_document"), stageOf("translate_chunks")],
        }),
      ),
    }),
  );
  expect(await screen.findByText("論文術語")).toBeInTheDocument();
  expect(screen.getByText("通用詞")).toBeInTheDocument();
  expect(screen.queryByText("動畫名詞")).toBeNull();
});

test("checking a global table marks the page dirty and saves the selection", async () => {
  const client = render();
  const check = await screen.findByRole("checkbox", { name: /通用詞/ });
  await userEvent.click(check);
  expect(await screen.findByText("變更尚未套用")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() =>
    expect(client.setTaskGlossary).toHaveBeenCalledWith("default", "t1", {
      global_ids: ["anime-terms", "shared"],
      use_task: false,
      asr_mode: "auto",
    }),
  );
});

test("the asr bias mode round-trips through save", async () => {
  const client = render();
  await userEvent.click(await screen.findByRole("radio", { name: /強制/ }));
  await userEvent.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() =>
    expect(client.setTaskGlossary).toHaveBeenCalledWith(
      "default",
      "t1",
      expect.objectContaining({ asr_mode: "force" }),
    ),
  );
});

test("the task-local table edits and writes its entries", async () => {
  const client = render(
    api({
      showTask: vi.fn().mockResolvedValue(
        task({ glossary: { global_ids: [], use_task: true, asr_mode: "auto" } }),
      ),
    }),
  );
  const sourceCell = await screen.findByDisplayValue("Kirito");
  await userEvent.clear(sourceCell);
  await userEvent.type(sourceCell, "Asuna");
  await userEvent.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(client.putTaskGlossaryEntries).toHaveBeenCalled());
  const entries = (client.putTaskGlossaryEntries as ReturnType<typeof vi.fn>).mock
    .calls[0][2];
  expect(entries[0].source).toBe("Asuna");
});

test("the reapply section offers the options this task actually supports", async () => {
  render();
  await userEvent.click(await screen.findByRole("checkbox", { name: /通用詞/ }));
  const section = await screen.findByRole("group", { name: "重新套用" });
  expect(within(section).getByRole("button", { name: /重跑 ASR/ })).toBeInTheDocument();
  expect(within(section).getByRole("button", { name: /名詞表校對/ })).toBeInTheDocument();
  expect(within(section).getByRole("button", { name: /重新翻譯/ })).toBeInTheDocument();
});

test("a task with no reapply options renders no empty reapply box", async () => {
  // A compose task has neither asr nor translate: the section would be a
  // frame around a single hint line.
  render(
    api({
      showTask: vi.fn().mockResolvedValue(
        task({
          profile: "audio-compose",
          input_path: "/tmp/lines.srt",
          stages: [stageOf("ingest_transcript"), stageOf("mix_audio")],
        }),
      ),
    }),
  );
  await userEvent.click(await screen.findByRole("checkbox", { name: /通用詞/ }));
  expect(await screen.findByText("變更尚未套用")).toBeInTheDocument();
  expect(screen.queryByText("重新套用")).toBeNull();
});

test("the global-table search filters tables, not the entry table", async () => {
  // The global search box and the task-local table shared one state, so
  // typing here filtered the entries below and left the table list untouched.
  render(
    api({
      showTask: vi.fn().mockResolvedValue(
        task({ glossary: { global_ids: [], use_task: true, asr_mode: "auto" } }),
      ),
    }),
  );
  expect(await screen.findByText("動畫名詞")).toBeInTheDocument();
  expect(screen.getByText("通用詞")).toBeInTheDocument();
  expect(await screen.findByDisplayValue("Kirito")).toBeInTheDocument();

  await userEvent.type(screen.getByRole("searchbox", { name: "搜尋名詞表" }), "通用");
  expect(screen.queryByText("動畫名詞")).toBeNull();
  expect(screen.getByText("通用詞")).toBeInTheDocument();
  // The task-local entry table stays put — no remote side effect.
  expect(screen.getByDisplayValue("Kirito")).toBeInTheDocument();
});

test("the entry search filters entries without hiding global tables", async () => {
  render(
    api({
      showTask: vi.fn().mockResolvedValue(
        task({ glossary: { global_ids: [], use_task: true, asr_mode: "auto" } }),
      ),
    }),
  );
  expect(await screen.findByDisplayValue("Kirito")).toBeInTheDocument();
  await userEvent.type(screen.getByRole("searchbox", { name: "搜尋" }), "Kir");
  expect(screen.queryByDisplayValue("Aincrad")).toBeNull();
  expect(screen.getByDisplayValue("Kirito")).toBeInTheDocument();
  expect(screen.getByText("動畫名詞")).toBeInTheDocument();
});

test("confirming a reapply posts the chosen mode", async () => {
  const client = render();
  await userEvent.click(await screen.findByRole("checkbox", { name: /通用詞/ }));
  await userEvent.click(await screen.findByRole("button", { name: /重跑 ASR/ }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "確認套用" }));
  await waitFor(() =>
    expect(client.reapplyGlossary).toHaveBeenCalledWith("default", "t1", "asr"),
  );
});
