import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

const openMock = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: (...args: unknown[]) => openMock(...args),
}));

import type { ApiClient } from "../lib/api/client";
import { renderWithConnection } from "../test/helpers";
import { ComposeDialog } from "./ComposeDialog";

const TASK_ROWS = [
  {
    id: "t-1",
    project: "default",
    status: "completed" as const,
    profile: "subtitle-translate",
    name: "第三集",
    created_at: "2026-07-16T10:00:00+00:00",
    updated_at: "2026-07-16T10:05:00+00:00",
  },
  {
    id: "t-2",
    project: "default",
    status: "completed" as const,
    profile: "av-dub",
    name: "第三集",
    created_at: "2026-07-18T09:00:00+00:00",
    updated_at: "2026-07-18T09:30:00+00:00",
  },
  {
    id: "t-3",
    project: "default",
    status: "pending" as const,
    profile: "av-default",
    name: "沒有產物的任務",
    created_at: "2026-07-19T09:00:00+00:00",
    updated_at: "2026-07-19T09:00:00+00:00",
  },
];

const ARTIFACTS = [
  {
    file: "06-subtitles.srt",
    index: 6,
    name: "subtitles.srt",
    schema_version: null,
    size: 400,
    mtime: 0,
  },
  {
    file: "04-translation.json",
    index: 4,
    name: "translation.json",
    schema_version: 1,
    size: 900,
    mtime: 0,
  },
];

function makeApi(extra: Partial<ApiClient> = {}): Partial<ApiClient> {
  return {
    listTasks: vi.fn().mockResolvedValue(TASK_ROWS),
    listArtifacts: vi.fn(async (_project: string, taskId: string) =>
      taskId === "t-3" ? [] : ARTIFACTS,
    ),
    ...extra,
  };
}

test("Tab is trapped inside the compose dialog", async () => {
  renderWithConnection(
    <ComposeDialog kind="audio" onClose={() => {}} onCreated={() => {}} />,
    { api: makeApi() },
  );
  await screen.findByText("製作音頻");
  const dialog = screen.getByRole("dialog");
  const nodes = dialog.querySelectorAll<HTMLElement>(
    "button:not([disabled]), input:not([disabled]), select:not([disabled])",
  );
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  last.focus();
  await userEvent.tab();
  expect(document.activeElement).toBe(first);
  first.focus();
  await userEvent.tab({ shift: true });
  expect(document.activeElement).toBe(last);
});

test("audio compose sends the transcript file and the audio profile", async () => {
  openMock.mockResolvedValue("/tmp/lines.srt");
  const createTask = vi.fn().mockResolvedValue({ id: "c1", project: "default" });
  const onCreated = vi.fn();
  renderWithConnection(
    <ComposeDialog kind="audio" onClose={() => {}} onCreated={onCreated} />,
    { api: makeApi({ createTask }) },
  );

  expect(await screen.findByText("製作音頻")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "選擇逐字稿" }));
  await waitFor(() =>
    expect(screen.getByDisplayValue("/tmp/lines.srt")).toBeInTheDocument(),
  );
  await userEvent.click(screen.getByRole("button", { name: "建立" }));

  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith({
      profile: "audio-compose",
      project: "default",
      transcript: { kind: "file", path: "/tmp/lines.srt" },
    }),
  );
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("default", "c1"));
});

test("video compose sends the video as input and the transcript as a param", async () => {
  const createTask = vi.fn().mockResolvedValue({ id: "c2", project: "default" });
  renderWithConnection(
    <ComposeDialog kind="video" onClose={() => {}} onCreated={() => {}} />,
    { api: makeApi({ createTask }) },
  );

  expect(await screen.findByText("製作影片")).toBeInTheDocument();
  openMock.mockResolvedValue("/tmp/clip.mp4");
  await userEvent.click(screen.getByRole("button", { name: "選擇影片" }));
  await waitFor(() =>
    expect(screen.getByDisplayValue("/tmp/clip.mp4")).toBeInTheDocument(),
  );
  openMock.mockResolvedValue("/tmp/lines.srt");
  await userEvent.click(screen.getByRole("button", { name: "選擇逐字稿" }));
  await waitFor(() =>
    expect(screen.getByDisplayValue("/tmp/lines.srt")).toBeInTheDocument(),
  );
  await userEvent.click(screen.getByRole("button", { name: "建立" }));

  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        profile: "video-compose",
        input_path: "/tmp/clip.mp4",
        transcript: { kind: "file", path: "/tmp/lines.srt" },
      }),
    ),
  );
});

test("video compose cannot be submitted without a video file", async () => {
  openMock.mockResolvedValue("/tmp/lines.srt");
  renderWithConnection(
    <ComposeDialog kind="video" onClose={() => {}} onCreated={() => {}} />,
    { api: makeApi() },
  );

  await screen.findByText("製作影片");
  await userEvent.click(screen.getByRole("button", { name: "選擇逐字稿" }));
  await waitFor(() =>
    expect(screen.getByDisplayValue("/tmp/lines.srt")).toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: "建立" })).toBeDisabled();
});

test("the create button stays disabled until a transcript is chosen", async () => {
  renderWithConnection(
    <ComposeDialog kind="audio" onClose={() => {}} onCreated={() => {}} />,
    { api: makeApi() },
  );
  await screen.findByText("製作音頻");
  expect(screen.getByRole("button", { name: "建立" })).toBeDisabled();
});

test("the task-artifact source lists transcript artifacts and sends the source", async () => {
  const createTask = vi.fn().mockResolvedValue({ id: "c3", project: "default" });
  renderWithConnection(
    <ComposeDialog kind="audio" onClose={() => {}} onCreated={() => {}} />,
    { api: makeApi({ createTask }) },
  );

  await screen.findByText("製作音頻");
  await userEvent.click(screen.getByRole("button", { name: "既有任務產物" }));
  await waitFor(() =>
    expect(screen.getByLabelText("來源任務")).toBeInTheDocument(),
  );
  const artifactSelect = await screen.findByLabelText("逐字稿產物");
  // A translation document is a valid compose source; ingest_transcript
  // reads its target text.
  expect(within(artifactSelect).getByText("04-translation.json")).toBeInTheDocument();
  await userEvent.selectOptions(artifactSelect, "06-subtitles.srt");
  await userEvent.click(screen.getByRole("button", { name: "建立" }));

  await waitFor(() =>
    expect(createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        profile: "audio-compose",
        transcript: {
          kind: "task",
          project: "default",
          task_id: "t-1",
          file: "06-subtitles.srt",
        },
      }),
    ),
  );
  const body = createTask.mock.calls[0][0] as Record<string, unknown>;
  // The server resolves the artifact into the task input; the app cannot.
  expect(body.input_path).toBeUndefined();
});

test("cancel closes the dialog", async () => {
  const onClose = vi.fn();
  renderWithConnection(
    <ComposeDialog kind="audio" onClose={onClose} onCreated={() => {}} />,
    { api: makeApi() },
  );
  await screen.findByText("製作音頻");
  await userEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(onClose).toHaveBeenCalled();
});


// --- L5: source task legibility and filtering -------------------------------

test("source tasks are identified by profile and date, not name alone", async () => {
  renderWithConnection(
    <ComposeDialog kind="audio" onClose={() => {}} onCreated={() => {}} />,
    { api: makeApi() },
  );
  await screen.findByText("製作音頻");
  await userEvent.click(screen.getByRole("button", { name: "既有任務產物" }));
  const select = await screen.findByLabelText("來源任務");
  // Two tasks share the name "第三集"; the option text has to tell them apart.
  const options = within(select).getAllByRole("option");
  const labels = options.map((option) => option.textContent ?? "");
  expect(labels.some((label) => label.includes("subtitle-translate"))).toBe(true);
  expect(labels.some((label) => label.includes("av-dub"))).toBe(true);
  expect(new Set(labels).size).toBe(labels.length);
});

test("tasks with no transcript artifact are left out of the list", async () => {
  renderWithConnection(
    <ComposeDialog kind="audio" onClose={() => {}} onCreated={() => {}} />,
    { api: makeApi() },
  );
  await screen.findByText("製作音頻");
  await userEvent.click(screen.getByRole("button", { name: "既有任務產物" }));
  const select = await screen.findByLabelText("來源任務");
  await waitFor(() =>
    expect(within(select).queryByText(/沒有產物的任務/)).toBeNull(),
  );
  expect(within(select).getAllByRole("option").length).toBe(2);
});
