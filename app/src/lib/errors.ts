import { t, type MessageKey } from "../i18n";

// Stage failures surface as raw exception strings from the core. Map the
// common failure families to human wording plus a next step; the raw text
// stays available behind a disclosure so nothing is hidden.
const PATTERNS: { pattern: RegExp; summary: MessageKey; hint: MessageKey }[] = [
  {
    pattern: /budget|預算/i,
    summary: "error.budget.summary",
    hint: "error.budget.hint",
  },
  {
    pattern: /401|403|unauthorized|forbidden|invalid[_ ]?api[_ ]?key|incorrect api key|authentication/i,
    summary: "error.auth.summary",
    hint: "error.auth.hint",
  },
  {
    pattern: /api[_ ]?key.*(not set|missing|empty)|env var|environment variable/i,
    summary: "error.keyMissing.summary",
    hint: "error.keyMissing.hint",
  },
  {
    pattern:
      /model[_ ]?not[_ ]?found|does not exist|no such model|unknown model|invalid model|model.*(not found|unavailable)/i,
    summary: "error.model.summary",
    hint: "error.model.hint",
  },
  {
    // Ahead of the rate-limit rule, whose "insufficient" would otherwise
    // claim "insufficient disk space" and send the user to check billing.
    pattern: /disk space|insufficient disk/i,
    summary: "error.disk.summary",
    hint: "error.disk.hint",
  },
  {
    pattern: /429|rate.?limit|quota|insufficient|exceeded your current quota|billing/i,
    summary: "error.rateLimit.summary",
    hint: "error.rateLimit.hint",
  },
  {
    pattern: /ffmpeg|ffprobe/i,
    summary: "error.ffmpeg.summary",
    hint: "error.ffmpeg.hint",
  },
  {
    pattern: /timeout|timed out|connection|econnrefused|network|dns|unreachable|ssl/i,
    summary: "error.network.summary",
    hint: "error.network.hint",
  },
  {
    pattern: /no such file|not found.*input|input.*not found|file.*missing/i,
    summary: "error.inputMissing.summary",
    hint: "error.inputMissing.hint",
  },
  {
    pattern: /pdf ?engine is not installed/i,
    summary: "error.pdfEngine.summary",
    hint: "error.pdfEngine.hint",
  },
  {
    pattern: /dubbing engine is not installed/i,
    summary: "error.dubEngine.summary",
    hint: "error.dubEngine.hint",
  },
  {
    pattern: /engine not available/i,
    summary: "error.engineUnavailable.summary",
    hint: "error.engineUnavailable.hint",
  },
  {
    pattern: /chunks (are not translated|failed translation)/i,
    summary: "error.docChunks.summary",
    hint: "error.docChunks.hint",
  },
  {
    pattern: /dub requires a timestamped transcript/i,
    summary: "error.dubTimestamps.summary",
    hint: "error.dubTimestamps.hint",
  },
  {
    pattern: /no dub mix|dub-mix\.wav artifact/i,
    summary: "error.dubMixMissing.summary",
    hint: "error.dubMixMissing.hint",
  },
];

export interface HumanError {
  summary: string;
  hint: string | null;
}

export function matchError(raw: string): HumanError | null {
  for (const { pattern, summary, hint } of PATTERNS) {
    if (pattern.test(raw)) {
      return { summary: t(summary), hint: t(hint) };
    }
  }
  return null;
}

export function humanizeError(raw: string): HumanError {
  return matchError(raw) ?? { summary: t("error.generic.summary"), hint: null };
}
