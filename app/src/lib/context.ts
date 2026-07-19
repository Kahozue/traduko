import type { CoreConfigDoc } from "./api/types";

// Rough token estimate for the context gauge: CJK is ~1 token per
// character, everything else ~4 characters per token. This is a display
// estimate, never used for billing or limits.
const CJK_RE = /[\u3000-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uAC00-\uD7AF]/;

export function estimateTokens(text: string): number {
  let cjk = 0;
  let other = 0;
  for (const ch of text) {
    if (CJK_RE.test(ch)) cjk += 1;
    else other += 1;
  }
  return cjk + Math.ceil(other / 4);
}

// The assistant's fixed prompt overhead (system prompt + tool specs),
// counted so a fresh conversation does not read as an empty context.
const BASE_OVERHEAD_TOKENS = 2000;

export interface ContextInfo {
  used: number;
  window: number;
  ratio: number;
}

// Mirrors the core's _resolve_default_llm rule: the provider chosen in
// settings (default_provider) wins, then the "default" key, then a sole
// entry, then the first key in sorted order.
export function assistantContextInfo(
  config: CoreConfigDoc | undefined,
  messages: { text: string }[],
): ContextInfo | null {
  const providers = config?.llm_providers ?? {};
  const names = Object.keys(providers);
  if (names.length === 0) return null;
  const chosen = config?.default_provider;
  const key =
    chosen && names.includes(chosen)
      ? chosen
      : names.includes("default")
        ? "default"
        : names.length === 1
          ? names[0]
          : [...names].sort()[0];
  const window = Number(
    (providers[key] as { context_window?: unknown }).context_window,
  );
  if (!Number.isFinite(window) || window <= 0) return null;
  const used =
    BASE_OVERHEAD_TOKENS +
    messages.reduce((sum, message) => sum + estimateTokens(message.text), 0);
  return { used, window, ratio: Math.min(1, used / window) };
}
