import { describe, expect, test } from "vitest";
import { stageStatusLabel, stageTypeLabel } from "./labels";

describe("stageTypeLabel", () => {
  test("maps built-in stage types to zh-TW", () => {
    expect(stageTypeLabel("ingest_subtitle")).toBe("讀入字幕");
    expect(stageTypeLabel("translate")).toBe("翻譯");
    expect(stageTypeLabel("proofread")).toBe("AI 校對");
    expect(stageTypeLabel("export_subtitles")).toBe("輸出字幕");
  });

  test("falls back to the raw type for unknown stages", () => {
    expect(stageTypeLabel("my_custom_stage")).toBe("my_custom_stage");
  });
});

describe("stageStatusLabel", () => {
  test("maps stage statuses to zh-TW", () => {
    expect(stageStatusLabel("completed")).toBe("已完成");
    expect(stageStatusLabel("skipped")).toBe("已略過");
  });

  test("falls back to the raw status when unknown", () => {
    expect(stageStatusLabel("weird")).toBe("weird");
  });
});
