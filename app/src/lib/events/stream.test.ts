import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { EventPayload } from "../api/types";
import { EventStream } from "./stream";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function makeStream(onEvent: (event: EventPayload) => void): EventStream {
  return new EventStream("ws://test/ws/events?token=t", {
    onEvent,
    factory: (url) => new FakeSocket(url) as unknown as WebSocket,
  });
}

test("delivers parsed events", () => {
  const events: EventPayload[] = [];
  const stream = makeStream((event) => events.push(event));
  stream.start();
  const socket = FakeSocket.instances[0];
  socket.onopen?.();
  socket.onmessage?.({
    data: JSON.stringify({ ts: "now", type: "task_started", task_id: "t1", project: "p", data: {} }),
  });
  expect(events).toHaveLength(1);
  expect(events[0].type).toBe("task_started");
  stream.stop();
});

test("reconnects with backoff after close", () => {
  const stream = makeStream(() => {});
  stream.start();
  expect(FakeSocket.instances).toHaveLength(1);
  FakeSocket.instances[0].onclose?.();
  vi.advanceTimersByTime(500);
  expect(FakeSocket.instances).toHaveLength(2);
  FakeSocket.instances[1].onclose?.();
  vi.advanceTimersByTime(999);
  expect(FakeSocket.instances).toHaveLength(2);
  vi.advanceTimersByTime(1);
  expect(FakeSocket.instances).toHaveLength(3);
  stream.stop();
});

test("stop prevents reconnect", () => {
  const stream = makeStream(() => {});
  stream.start();
  stream.stop();
  FakeSocket.instances[0].onclose?.();
  vi.advanceTimersByTime(60_000);
  expect(FakeSocket.instances).toHaveLength(1);
});
