import { describe, expect, test } from "vitest";
import seeds from "../../../core/src/traduko/seeds.py?raw";
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

  // Every stage type shipped in the core's seed profiles must have a label
  // key wired up, so a new pipeline stage cannot leak a raw English ID into
  // the stage list again (QA v3 M1: export_transcript/export_audio).
  test("covers the stage types appended outside of seed profiles", () => {
    // glossary_proofread is inserted next to asr, export_video and
    // export_audio_custom are appended by the export studio; none of them
    // appear in a seed profile, so the seed sweep below never sees them.
    for (const type of [
      "glossary_proofread",
      "export_video",
      "export_audio_custom",
    ]) {
      expect(stageTypeLabel(type), `missing label for stage type "${type}"`).not.toBe(
        type,
      );
    }
  });

  test("covers every stage type in the core seed profiles", () => {
    const types = new Set(
      [...seeds.matchAll(/^\s*- type: (\w+)$/gm)].map((match) => match[1]),
    );
    expect(types.size).toBeGreaterThan(0);
    for (const type of types) {
      expect(stageTypeLabel(type), `missing label for stage type "${type}"`).not.toBe(
        type,
      );
    }
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
