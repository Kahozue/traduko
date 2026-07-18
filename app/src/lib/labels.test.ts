import { describe, expect, test } from "vitest";
import {
  eventTypeLabel,
  stageListLabels,
  stageStatusLabel,
  stageTypeLabel,
} from "./labels";

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

describe("stageListLabels", () => {
  test("marks repeated translate/qc rounds as retries", () => {
    const labels = stageListLabels([
      { type: "ingest_document" },
      { type: "chunk" },
      { type: "translate_chunks" },
      { type: "qc_scan" },
      { type: "translate_chunks" },
      { type: "qc_scan" },
      { type: "export_document" },
    ]);
    expect(labels).toEqual([
      "讀入文件",
      "分塊",
      "翻譯文件",
      "品質檢測",
      "翻譯文件（重試）",
      "品質檢測（重試）",
      "輸出文件",
    ]);
  });

  test("repeats of other stage types keep their plain label", () => {
    expect(stageListLabels([{ type: "translate" }, { type: "translate" }])).toEqual([
      "翻譯",
      "翻譯",
    ]);
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

test("event type labels localize known types and fall back", () => {
  expect(eventTypeLabel("task_completed")).toBe("任務完成");
  expect(eventTypeLabel("mystery_event")).toBe("mystery_event");
});
