import { expect, test } from "vitest";
import type { EventPayload } from "../api/types";
import { EventLog } from "./store";

function event(partial: Partial<EventPayload>): EventPayload {
  return { ts: "now", type: "task_started", task_id: "t1", project: "p", data: {}, ...partial };
}

test("accumulates events per task and tracks stage progress", () => {
  const log = new EventLog();
  log.push(event({ type: "task_started", data: { stage_total: 2 } }));
  log.push(event({ type: "stage_progress", data: { stage_index: 0, current: 3, total: 10 } }));
  const live = log.get("p", "t1");
  expect(live?.events).toHaveLength(2);
  expect(live?.stageProgress).toEqual({ current: 3, total: 10 });

  log.push(event({ type: "stage_completed", data: { stage_index: 0, stage_total: 2 } }));
  expect(log.get("p", "t1")?.stageProgress).toBeNull();
  expect(log.get("p", "other")).toBeUndefined();
});

test("caps stored events and notifies subscribers", () => {
  const log = new EventLog();
  let notified = 0;
  const unsubscribe = log.subscribe(() => {
    notified += 1;
  });
  for (let i = 0; i < 250; i += 1) {
    log.push(event({ type: "stage_progress", data: { stage_index: 0, current: i, total: 250 } }));
  }
  expect(log.get("p", "t1")?.events).toHaveLength(200);
  expect(notified).toBe(250);
  unsubscribe();
  log.push(event({}));
  expect(notified).toBe(250);
});
