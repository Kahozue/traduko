import { useSyncExternalStore } from "react";
import type { EventPayload } from "../api/types";

export interface TaskLive {
  events: EventPayload[];
  stageProgress: { current: number; total: number } | null;
}

const MAX_EVENTS_PER_TASK = 200;

export class EventLog {
  private byTask = new Map<string, TaskLive>();
  private listeners = new Set<() => void>();

  push(event: EventPayload): void {
    const key = `${event.project}/${event.task_id}`;
    const prev = this.byTask.get(key) ?? { events: [], stageProgress: null };
    const events = [...prev.events, event].slice(-MAX_EVENTS_PER_TASK);
    let stageProgress = prev.stageProgress;
    if (event.type === "stage_progress") {
      stageProgress = { current: Number(event.data.current), total: Number(event.data.total) };
    } else if (event.type === "stage_completed") {
      stageProgress = null;
    }
    this.byTask.set(key, { events, stageProgress });
    for (const listener of this.listeners) listener();
  }

  get(project: string, taskId: string): TaskLive | undefined {
    return this.byTask.get(`${project}/${taskId}`);
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}

export const eventLog = new EventLog();

export function useTaskLive(project: string, taskId: string): TaskLive | undefined {
  return useSyncExternalStore(
    (listener) => eventLog.subscribe(listener),
    () => eventLog.get(project, taskId),
  );
}

// ---------------------------------------------------------------------------
// Assistant live-progress feed: the in-flight turn's narrative, stream buffer
// and tool activity, fed by assistant_* events on the same socket. History
// persistence stays with the POST response; this store only carries what the
// panel shows while the turn runs.

export interface AssistantLiveState {
  sessionId: string | null;
  running: boolean;
  round: number;
  // Completed narrative texts of the in-flight turn, in order.
  texts: string[];
  // Delta accumulator for the sentence currently streaming in.
  streaming: string;
  tool: { name: string; kind: string } | null;
  // Bumped per authorization request so the panel can refetch proposals.
  proposalVersion: number;
}

const ASSISTANT_EMPTY: AssistantLiveState = {
  sessionId: null,
  running: false,
  round: 0,
  texts: [],
  streaming: "",
  tool: null,
  proposalVersion: 0,
};

export class AssistantLiveStore {
  private state: AssistantLiveState = ASSISTANT_EMPTY;
  private listeners = new Set<() => void>();

  push(event: EventPayload): void {
    const data = event.data as Record<string, unknown>;
    const prev = this.state;
    let next = prev;
    switch (event.type) {
      case "assistant_round": {
        const round = Number(data.round ?? 1);
        next =
          round <= 1
            ? {
                ...ASSISTANT_EMPTY,
                proposalVersion: prev.proposalVersion,
                sessionId: event.task_id,
                running: true,
                round: 1,
              }
            : { ...prev, round, running: true };
        break;
      }
      case "assistant_delta":
        next = { ...prev, running: true, streaming: prev.streaming + String(data.text ?? "") };
        break;
      case "assistant_text":
        next = { ...prev, texts: [...prev.texts, String(data.text ?? "")], streaming: "" };
        break;
      case "assistant_tool_started":
        next = {
          ...prev,
          streaming: "",
          tool: { name: String(data.tool ?? ""), kind: String(data.kind ?? "execute") },
        };
        break;
      case "assistant_tool_finished":
        next = { ...prev, tool: null };
        break;
      case "assistant_authorization_required":
        next = { ...prev, proposalVersion: prev.proposalVersion + 1 };
        break;
      case "assistant_done":
        next = { ...prev, running: false, tool: null, streaming: "" };
        break;
      default:
        return;
    }
    this.state = next;
    for (const listener of this.listeners) listener();
  }

  reset(): void {
    this.state = { ...ASSISTANT_EMPTY, proposalVersion: this.state.proposalVersion };
    for (const listener of this.listeners) listener();
  }

  getState = (): AssistantLiveState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
}

export const assistantLive = new AssistantLiveStore();

export function useAssistantLive(): AssistantLiveState {
  return useSyncExternalStore(assistantLive.subscribe, assistantLive.getState);
}
