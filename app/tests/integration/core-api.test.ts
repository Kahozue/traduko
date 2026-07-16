import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterAll, beforeAll, expect, test } from "vitest";
import { ApiClient } from "../../src/lib/api/client";
import { EventStream } from "../../src/lib/events/stream";
import type { EventPayload } from "../../src/lib/api/types";

const PORT = 18686;
const CORE_DIR = resolve(__dirname, "../../../core");

let dataRoot: string;
let coreProcess: ChildProcess;
let client: ApiClient;

function sleep(ms: number): Promise<void> {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

beforeAll(async () => {
  dataRoot = mkdtempSync(join(tmpdir(), "traduko-app-integration-"));
  coreProcess = spawn("uv", ["run", "traduko", "serve", "--port", String(PORT)], {
    cwd: CORE_DIR,
    env: { ...process.env, TRADUKO_DATA_ROOT: dataRoot },
    stdio: "ignore",
  });
  let healthy = false;
  for (let i = 0; i < 100; i += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/health`);
      if (response.ok) {
        healthy = true;
        break;
      }
    } catch {
      // server not up yet
    }
    await sleep(200);
  }
  if (!healthy) throw new Error("core did not become healthy");

  const token = readFileSync(join(dataRoot, "config", "api-token"), "utf-8").trim();
  client = new ApiClient(`http://127.0.0.1:${PORT}`, token);

  mkdirSync(join(dataRoot, "profiles"), { recursive: true });
  writeFileSync(
    join(dataRoot, "profiles", "passthrough.yaml"),
    "schema_version: 1\nname: passthrough\nstages:\n  - type: noop\n",
    "utf-8",
  );
  writeFileSync(join(dataRoot, "in.srt"), "1\n00:00:00,000 --> 00:00:01,000\nhi\n", "utf-8");
});

afterAll(() => {
  coreProcess?.kill("SIGTERM");
  rmSync(dataRoot, { recursive: true, force: true });
});

test("full round trip: create, run, stream events, complete", async () => {
  const events: EventPayload[] = [];
  const stream = new EventStream(client.wsUrl(), { onEvent: (event) => events.push(event) });
  stream.start();
  await sleep(300);

  const task = await client.createTask({
    input_path: join(dataRoot, "in.srt"),
    profile: "passthrough",
  });
  expect(task.status).toBe("pending");

  const report = await client.preflight(task.project, task.id);
  expect(report.ok).toBe(true);

  const queued = await client.runTask(task.project, task.id);
  expect(queued.queued).toBe(true);

  let finalStatus = "";
  for (let i = 0; i < 100; i += 1) {
    const shown = await client.showTask(task.project, task.id);
    finalStatus = shown.status;
    if (["completed", "failed", "canceled"].includes(finalStatus)) break;
    await sleep(100);
  }
  expect(finalStatus).toBe("completed");

  for (let i = 0; i < 50 && !events.some((event) => event.type === "task_completed"); i += 1) {
    await sleep(100);
  }
  stream.stop();

  const types = events.map((event) => event.type);
  expect(types[0]).toBe("task_started");
  expect(types).toContain("task_completed");

  const rows = await client.listTasks();
  expect(rows.map((row) => row.id)).toContain(task.id);
});
