import { describe, expect, it, test } from "vitest";
import type { EventPayload } from "../api/types";
import { AssistantLiveStore, EventLog } from "./store";

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

describe("AssistantLiveStore", () => {
  function make() {
    // Fresh instance per test; the module also exports a singleton.
    return new AssistantLiveStore();
  }
  const base = { ts: "t", project: "assistant", task_id: "s1", data: {} };

  it("accumulates deltas and finalizes narrative texts", () => {
    const store = make();
    store.push({ ...base, type: "assistant_round", data: { round: 1 } } as never);
    expect(store.getState().running).toBe(true);
    store.push({ ...base, type: "assistant_delta", data: { text: "先看" } } as never);
    store.push({ ...base, type: "assistant_delta", data: { text: "狀態。" } } as never);
    expect(store.getState().streaming).toBe("先看狀態。");
    store.push({ ...base, type: "assistant_text", data: { text: "先看狀態。" } } as never);
    expect(store.getState().texts).toEqual(["先看狀態。"]);
    expect(store.getState().streaming).toBe("");
  });

  it("tracks tool activity and clears on finish", () => {
    const store = make();
    store.push({ ...base, type: "assistant_tool_started", data: { tool: "list_tasks", kind: "read" } } as never);
    expect(store.getState().tool).toEqual({ name: "list_tasks", kind: "read" });
    store.push({ ...base, type: "assistant_tool_finished", data: { tool: "list_tasks", ok: true } } as never);
    expect(store.getState().tool).toBeNull();
  });

  it("round 1 resets a previous run and done stops it", () => {
    const store = make();
    store.push({ ...base, type: "assistant_round", data: { round: 1 } } as never);
    store.push({ ...base, type: "assistant_text", data: { text: "old" } } as never);
    store.push({ ...base, type: "assistant_done", data: { converged: true } } as never);
    expect(store.getState().running).toBe(false);
    store.push({ ...base, type: "assistant_round", data: { round: 1 } } as never);
    expect(store.getState().texts).toEqual([]);
    expect(store.getState().running).toBe(true);
  });

  it("bumps proposalVersion on authorization events", () => {
    const store = make();
    expect(store.getState().proposalVersion).toBe(0);
    store.push({ ...base, type: "assistant_authorization_required", data: { proposal_id: "p1" } } as never);
    expect(store.getState().proposalVersion).toBe(1);
  });
});
