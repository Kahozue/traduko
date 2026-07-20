import { expect, test } from "vitest";
import { humanizeError, matchError } from "./errors";

test("maps common failure families to human wording", () => {
  expect(humanizeError("HTTP 401 Unauthorized: invalid api key").summary).toBe(
    "LLM 供應商拒絕請求（金鑰無效或權限不足）",
  );
  expect(humanizeError("ffmpeg not found on PATH").summary).toBe("ffmpeg 不可用");
  expect(humanizeError("Connection timed out after 30s").summary).toBe("網路連線問題");
  expect(humanizeError("budget exceeded for task").summary).toBe("預算觸頂");
  expect(humanizeError("HTTP 429 rate limit reached").summary).toBe(
    "供應商限流或額度用盡",
  );
});

test("pdf engine missing maps to a localized summary and hint", () => {
  const human = humanizeError(
    "pdf engine is not installed; install it from the settings document tab",
  );
  expect(human.summary).toBe("PDF 引擎尚未安裝");
  expect(human.hint).toContain("設定");
});

test("untranslated chunks map to a localized summary", () => {
  expect(
    humanizeError(
      "cannot export: 3 of 40 chunks are not translated; re-run translation "
        + "or fix them in the text editor",
    ).summary,
  ).toBe("部分段落尚未翻譯");
  expect(
    humanizeError(
      "2 of 5 chunks failed translation; check the llm provider in settings "
        + "or fix them in the text editor, then run again",
    ).summary,
  ).toBe("部分段落尚未翻譯");
});

test("dubbing engine missing maps to a localized summary pointing at settings", () => {
  const human = humanizeError(
    "dubbing engine is not installed; install it from the settings video tab",
  );
  expect(human.summary).toBe("配音引擎尚未安裝");
  expect(human.hint).toContain("設定");
});

test("a placeholder engine selection maps to its own summary", () => {
  const human = humanizeError("engine not available: cloud_placeholder");
  expect(human.summary).toBe("所選引擎尚不可用");
  expect(human.hint).toContain("引擎");
});

test("insufficient disk space maps to a localized summary", () => {
  expect(humanizeError("insufficient disk space for export").summary).toBe(
    "磁碟空間不足",
  );
  expect(humanizeError("not enough disk space: need 2.0 GB, 300 MB free").summary).toBe(
    "磁碟空間不足",
  );
});

test("matchError returns null for unknown text instead of a generic summary", () => {
  expect(matchError("SomethingWeirdError: xyzzy")).toBeNull();
  expect(matchError("ffmpeg not found on PATH")?.summary).toBe("ffmpeg 不可用");
});

test("unknown errors fall back to a generic summary without a hint", () => {
  const human = humanizeError("SomethingWeirdError: xyzzy");
  expect(human.summary).toBe("階段執行失敗");
  expect(human.hint).toBeNull();
});
