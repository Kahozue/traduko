import { expect, test } from "vitest";
import contract from "./labels.contract.json";
import { EVENT_TYPE_KEYS, STAGE_STATUS_KEYS, STAGE_TYPE_KEYS } from "./labels";
import { STATUS_KEYS } from "../components/StatusBadge";

// CI assertion 2 (app half): every core enum in labels.contract.json has an
// app label entry. The core half (core/tests/test_labels_contract.py) keeps
// the contract honest against core's real enums; this half keeps the app
// honest against the contract. Together they catch the R3 M1 defect -- a core
// stage/event/status that ships without an app label. i18n three-locale
// parity is already covered by i18n/index.test.ts, so this only checks the
// core -> app-label-map hop, the one nothing else guards. The contract JSON
// lives app-side so this test needs no filesystem access (which the
// production build's tsc would reject); the Python half reaches across to it.

test("every core stage type has an app label", () => {
  const missing = contract.stage_types.filter((s) => !(s in STAGE_TYPE_KEYS));
  expect(missing, "core stages with no app label (add to STAGE_TYPE_KEYS + i18n)").toEqual([]);
});

test("every core UI event type has an app label", () => {
  const missing = contract.event_types_ui.filter((e) => !(e in EVENT_TYPE_KEYS));
  expect(missing, "core events with no app label (add to EVENT_TYPE_KEYS + i18n)").toEqual([]);
});

test("every core stage status has an app label", () => {
  const missing = contract.stage_statuses.filter((s) => !(s in STAGE_STATUS_KEYS));
  expect(missing, "core stage statuses with no app label (add to STAGE_STATUS_KEYS)").toEqual([]);
});

test("every core task status has a StatusBadge label", () => {
  const missing = contract.task_statuses.filter((s) => !(s in STATUS_KEYS));
  expect(missing, "core task statuses with no StatusBadge label").toEqual([]);
});
