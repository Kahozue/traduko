import { expect, test } from "vitest";
import { humanizeError } from "./errors";

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

test("unknown errors fall back to a generic summary without a hint", () => {
  const human = humanizeError("SomethingWeirdError: xyzzy");
  expect(human.summary).toBe("階段執行失敗");
  expect(human.hint).toBeNull();
});
