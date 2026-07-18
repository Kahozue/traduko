import { expect, test, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithConnection } from "../test/helpers";
import type { ApiClient } from "../lib/api/client";
import { SpeakerReviewView } from "./SpeakerReviewView";

const SPEAKERS = {
  schema_version: 1,
  speakers: [
    { id: "S1", label: "Speaker 1", ref_start: 4, ref_end: 9, ref_text: "long speech" },
    { id: "S2", label: "Speaker 2", ref_start: 2.2, ref_end: 3.8, ref_text: "hi back" },
  ],
  segments: [
    { id: 1, speaker: "S1" },
    { id: 2, speaker: "S2" },
    { id: 3, speaker: "S1" },
  ],
};

const TRANSLATION = {
  schema_version: 1,
  source_language: "en",
  target_language: "zh",
  segments: [
    { id: 1, start: 0, end: 2, source: "hello", target: "哈囉" },
    { id: 2, start: 2.2, end: 3.8, source: "hi back", target: "回嗨" },
    { id: 3, start: 4, end: 9, source: "long speech", target: "長篇" },
  ],
};

function makeApi(overrides: Partial<ApiClient> = {}): Partial<ApiClient> {
  return {
    readArtifact: vi.fn((_p: string, _t: string, name: string) => {
      if (name === "speakers.json") return Promise.resolve(SPEAKERS);
      return Promise.resolve(TRANSLATION);
    }) as unknown as ApiClient["readArtifact"],
    saveArtifact: vi.fn().mockResolvedValue({ file: "08-speakers.json", stages_reset: 4 }),
    ...overrides,
  };
}

test("renders speakers and per-segment assignment", async () => {
  renderWithConnection(
    <SpeakerReviewView project="p" taskId="t" onBack={() => {}} />,
    { api: makeApi() },
  );
  await waitFor(() =>
    expect(screen.getByLabelText("S1 名稱")).toBeInTheDocument(),
  );
  expect(screen.getByText("hello")).toBeInTheDocument();
  const seg1 = screen.getByLabelText("說話人 1") as HTMLSelectElement;
  expect(seg1.value).toBe("S1");
});

test("reassigning a segment marks dirty and saves the new assignment", async () => {
  const api = makeApi();
  renderWithConnection(
    <SpeakerReviewView project="p" taskId="t" onBack={() => {}} />,
    { api },
  );
  await screen.findByLabelText("S1 名稱");
  await userEvent.selectOptions(screen.getByLabelText("說話人 1"), "S2");
  await userEvent.click(screen.getByRole("button", { name: "存回" }));
  await waitFor(() => expect(api.saveArtifact).toHaveBeenCalled());
  const [, , name, body] = (api.saveArtifact as ReturnType<typeof vi.fn>).mock
    .calls[0];
  expect(name).toBe("speakers.json");
  expect(body.segments).toEqual([
    { id: 1, speaker: "S2" },
    { id: 2, speaker: "S2" },
    { id: 3, speaker: "S1" },
  ]);
});

test("merging a speaker reassigns its segments and drops it", async () => {
  const api = makeApi();
  renderWithConnection(
    <SpeakerReviewView project="p" taskId="t" onBack={() => {}} />,
    { api },
  );
  await screen.findByLabelText("S2 名稱");
  await userEvent.selectOptions(screen.getByLabelText("S2 合併到"), "S1");
  expect(screen.queryByLabelText("S2 名稱")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "存回" }));
  await waitFor(() => expect(api.saveArtifact).toHaveBeenCalled());
  const [, , , body] = (api.saveArtifact as ReturnType<typeof vi.fn>).mock.calls[0];
  expect(body.speakers).toHaveLength(1);
  expect(body.segments.every((s: { speaker: string }) => s.speaker === "S1")).toBe(
    true,
  );
});

test("renaming a speaker flows into the saved doc", async () => {
  const api = makeApi();
  renderWithConnection(
    <SpeakerReviewView project="p" taskId="t" onBack={() => {}} />,
    { api },
  );
  await screen.findByLabelText("S1 名稱");
  const input = screen.getByLabelText("S1 名稱");
  await userEvent.clear(input);
  await userEvent.type(input, "旁白");
  await userEvent.click(screen.getByRole("button", { name: "存回" }));
  await waitFor(() => expect(api.saveArtifact).toHaveBeenCalled());
  const [, , , body] = (api.saveArtifact as ReturnType<typeof vi.fn>).mock.calls[0];
  expect(body.speakers[0].label).toBe("旁白");
});

test("dirty state blocks leaving until confirmed", async () => {
  const onBack = vi.fn();
  renderWithConnection(
    <SpeakerReviewView project="p" taskId="t" onBack={onBack} />,
    { api: makeApi() },
  );
  await screen.findByLabelText("S1 名稱");
  await userEvent.selectOptions(screen.getByLabelText("說話人 1"), "S2");
  await userEvent.click(screen.getByRole("button", { name: "返回任務" }));
  expect(onBack).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "放棄修改" }));
  expect(onBack).toHaveBeenCalled();
});
