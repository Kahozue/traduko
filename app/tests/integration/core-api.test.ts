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

test("edit artifact: save new version reopens task and rerun completes", async () => {
  writeFileSync(
    join(dataRoot, "profiles", "subtitle-simple.yaml"),
    [
      "schema_version: 1",
      "name: subtitle-simple",
      "stages:",
      "  - type: ingest_subtitle",
      "  - type: translate",
      "    params:",
      "      provider: fake",
      "      target_language: en",
      "  - type: export_subtitles",
      "    params:",
      "      formats: [srt]",
    ].join("\n"),
    "utf-8",
  );
  writeFileSync(join(dataRoot, "in2.srt"), "1\n00:00:00,000 --> 00:00:01,000\nhola\n", "utf-8");

  const task = await client.createTask({
    input_path: join(dataRoot, "in2.srt"),
    profile: "subtitle-simple",
  });
  // A bare .srt carries no document or audio stage markers, so task_domain
  // falls through to "video", where translation defaults to off. This test is
  // about editing translation.json, so it asks for the stage explicitly rather
  // than riding on whatever the global default happens to be.
  await client.patchTaskSwitches(task.project, task.id, { translate: true });
  await client.runTask(task.project, task.id);

  const waitForTerminal = async (): Promise<string> => {
    let status = "";
    for (let i = 0; i < 100; i += 1) {
      status = (await client.showTask(task.project, task.id)).status;
      if (["completed", "failed", "canceled"].includes(status)) break;
      await sleep(100);
    }
    return status;
  };
  expect(await waitForTerminal()).toBe("completed");

  const translation = await client.readArtifact<{
    segments: { id: number; target: string }[];
  }>(task.project, task.id, "translation.json");
  expect(translation.segments.length).toBeGreaterThan(0);

  translation.segments[0].target = "手動改譯";
  const saved = await client.saveArtifact(task.project, task.id, "translation.json", translation);
  expect(saved.file).toMatch(/-translation\.json$/);
  expect(saved.stages_reset).toBeGreaterThanOrEqual(1);

  const reopened = await client.showTask(task.project, task.id);
  expect(reopened.status).toBe("pending");
  const exportStage = reopened.stages.find((s) => s.type === "export_subtitles");
  expect(exportStage?.status).toBe("pending");

  await client.runTask(task.project, task.id);
  expect(await waitForTerminal()).toBe("completed");

  const latest = await client.readArtifact<{ segments: { target: string }[] }>(
    task.project,
    task.id,
    "translation.json",
  );
  expect(latest.segments[0].target).toBe("手動改譯");
});

test("task name: create with custom name then rename", async () => {
  writeFileSync(join(dataRoot, "in3.srt"), "1\n00:00:00,000 --> 00:00:01,000\nyo\n", "utf-8");
  const task = await client.createTask({
    input_path: join(dataRoot, "in3.srt"),
    profile: "passthrough",
    name: "第三集",
  });
  expect(task.name).toBe("第三集");

  const renamed = await client.renameTask(task.project, task.id, "改名後");
  expect(renamed.name).toBe("改名後");

  const rows = await client.listTasks();
  const row = rows.find((r) => r.id === task.id);
  expect(row?.name).toBe("改名後");
});

test("config round trip persists budget and provider", async () => {
  const config = await client.getConfig();
  expect(config.default_project).toBe("default");

  config.budget.monthly_usd_limit = 30;
  config.llm_providers["deepseek"] = {
    type: "openai_compat",
    base_url: "https://api.deepseek.com/v1",
    api_key_env: "DEEPSEEK_API_KEY",
  };
  const saved = await client.saveConfig(config);
  expect(saved.budget.monthly_usd_limit).toBe(30);

  const reloaded = await client.getConfig();
  expect(reloaded.llm_providers["deepseek"]).toMatchObject({
    base_url: "https://api.deepseek.com/v1",
  });
  const budget = await client.budget();
  expect(budget.monthly_usd_limit).toBe(30);
});

test("discord bot config defaults and round trip", async () => {
  const config = await client.getConfig();
  expect(config.discord_bot.enabled).toBe(false);
  const edited = {
    ...config,
    discord_bot: { ...config.discord_bot, allowed_user_ids: ["345678901234567890"] },
  };
  const saved = await client.saveConfig(edited);
  expect(saved.discord_bot.allowed_user_ids).toEqual(["345678901234567890"]);
});

test("pause endpoint rejects idle tasks", async () => {
  const record = await client.createTask({
    input_path: join(dataRoot, "in.srt"),
    profile: "passthrough",
  });
  await expect(client.pauseTask(record.project, record.id)).rejects.toMatchObject({
    status: 409,
  });
});

test("sync config round trip and status when disabled", async () => {
  const config = await client.getConfig();
  expect(config.sync.enabled).toBe(false);
  expect(config.sync.mode).toBe("folder");

  const cloud = join(dataRoot, "cloud");
  const edited = {
    ...config,
    sync: { ...config.sync, enabled: true, mode: "folder" as const, folder_path: cloud },
  };
  const saved = await client.saveConfig(edited);
  expect(saved.sync.folder_path).toBe(cloud);

  const status = await client.getSyncStatus();
  expect(status.enabled).toBe(true);
  expect(status.peers).toEqual([]);

  const report = await client.runSync();
  expect(report.ok).toBe(true);
  expect(report.pushed).toContain("config/core.yaml");

  // Restore disabled state so a re-run is a 400.
  const reset = await client.saveConfig({
    ...saved,
    sync: { ...saved.sync, enabled: false },
  });
  expect(reset.sync.enabled).toBe(false);
  await expect(client.runSync()).rejects.toMatchObject({ status: 400 });
});
