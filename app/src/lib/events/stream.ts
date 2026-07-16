import type { EventPayload } from "../api/types";

export interface EventStreamOptions {
  onEvent: (event: EventPayload) => void;
  onStatus?: (status: "open" | "closed") => void;
  factory?: (url: string) => WebSocket;
}

const BASE_DELAY_MS = 500;
const MAX_DELAY_MS = 10_000;

export class EventStream {
  private socket: WebSocket | null = null;
  private attempts = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(
    private url: string,
    private options: EventStreamOptions,
  ) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.socket?.close();
    this.socket = null;
  }

  private connect(): void {
    const factory = this.options.factory ?? ((url: string) => new WebSocket(url));
    const socket = factory(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.attempts = 0;
      this.options.onStatus?.("open");
    };
    socket.onmessage = (message: MessageEvent) => {
      this.options.onEvent(JSON.parse(String(message.data)) as EventPayload);
    };
    socket.onclose = () => {
      this.options.onStatus?.("closed");
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = Math.min(BASE_DELAY_MS * 2 ** this.attempts, MAX_DELAY_MS);
    this.attempts += 1;
    this.timer = setTimeout(() => this.connect(), delay);
  }
}
