import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";

// CI assertion 2 (app half): every core enum in labels_contract.json has an
// app label entry. The core half (core/tests/test_labels_contract.py) keeps
// the contract honest against core's real enums; this half keeps the app
// honest against the contract. Together they catch the R3 M1 defect -- a core
// stage/event/status that ships without an app label. i18n three-locale
// parity is already covered by i18n/index.test.ts, so this only checks the
// core -> app-label-map hop, the one nothing else guards.

// vitest runs with cwd at the app package root (also true under CI's
// `pnpm test`). import.meta.url is not a file: URL here, so resolve from cwd.
const APP_ROOT = process.cwd();

const contract = JSON.parse(
  readFileSync(resolve(APP_ROOT, "../core/src/traduko/labels_contract.json"), "utf-8"),
) as {
  stage_types: string[];
  event_types_ui: string[];
  task_statuses: string[];
  stage_statuses: string[];
};

// Read the maps from source text rather than importing them: the maps are
// module-private, and this mirrors how i18n/index.test.ts reads locale files,
// so no source file grows an export purely for the test.
function mapKeys(file: string, mapName: string): Set<string> {
  const source = readFileSync(resolve(APP_ROOT, file), "utf-8");
  const start = source.indexOf(`const ${mapName}`);
  expect(start, `const ${mapName} not found in ${file}`).toBeGreaterThanOrEqual(0);
  const open = source.indexOf("{", start);
  const close = source.indexOf("};", open);
  expect(close, `could not find end of ${mapName} in ${file}`).toBeGreaterThan(open);
  const body = source.slice(open + 1, close);
  return new Set([...body.matchAll(/^\s{2}(\w+):/gm)].map((m) => m[1]));
}

test("every core stage type has an app label", () => {
  const keys = mapKeys("src/lib/labels.ts", "STAGE_TYPE_KEYS");
  const missing = contract.stage_types.filter((s) => !keys.has(s));
  expect(missing, "core stages with no app label (add to STAGE_TYPE_KEYS + i18n)").toEqual([]);
});

test("every core UI event type has an app label", () => {
  const keys = mapKeys("src/lib/labels.ts", "EVENT_TYPE_KEYS");
  const missing = contract.event_types_ui.filter((e) => !keys.has(e));
  expect(missing, "core events with no app label (add to EVENT_TYPE_KEYS + i18n)").toEqual([]);
});

test("every core stage status has an app label", () => {
  const keys = mapKeys("src/lib/labels.ts", "STAGE_STATUS_KEYS");
  const missing = contract.stage_statuses.filter((s) => !keys.has(s));
  expect(missing, "core stage statuses with no app label (add to STAGE_STATUS_KEYS)").toEqual([]);
});

test("every core task status has a StatusBadge label", () => {
  const keys = mapKeys("src/components/StatusBadge.tsx", "KEYS");
  const missing = contract.task_statuses.filter((s) => !keys.has(s));
  expect(missing, "core task statuses with no StatusBadge label").toEqual([]);
});
