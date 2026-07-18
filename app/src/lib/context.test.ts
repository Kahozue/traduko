import { describe, expect, it } from "vitest";
import { assistantContextInfo, estimateTokens } from "./context";

describe("estimateTokens", () => {
  it("counts CJK as one token per char and latin as quarter tokens", () => {
    expect(estimateTokens("你好世界")).toBe(4);
    expect(estimateTokens("abcdefgh")).toBe(2);
    expect(estimateTokens("")).toBe(0);
  });
});

describe("assistantContextInfo", () => {
  const config = {
    llm_providers: {
      zeta: { type: "openai_compat", model: "z", context_window: 1000 },
      default: { type: "openai_compat", model: "d", context_window: 8000 },
    },
  };

  it("uses the assistant's provider rule: default key first", () => {
    const info = assistantContextInfo(
      config as never,
      [{ text: "你好你好" }, { text: "okay" }],
    );
    expect(info).not.toBeNull();
    expect(info?.window).toBe(8000);
    expect(info?.used).toBeGreaterThan(0);
    expect(info?.ratio).toBeGreaterThan(0);
  });

  it("returns null without a context window or providers", () => {
    expect(assistantContextInfo(undefined, [])).toBeNull();
    expect(
      assistantContextInfo(
        { llm_providers: { a: { type: "openai_compat" } } } as never,
        [],
      ),
    ).toBeNull();
  });

  it("caps ratio at 1", () => {
    const tiny = { llm_providers: { a: { type: "openai_compat", context_window: 10 } } };
    const info = assistantContextInfo(tiny as never, [{ text: "很長的中文訊息".repeat(50) }]);
    expect(info?.ratio).toBe(1);
  });
});
