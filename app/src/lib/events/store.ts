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
