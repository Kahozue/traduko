import { expect, test, vi } from "vitest";
import { ApiClient, ApiError } from "./client";
import type { CoreConfigDoc } from "./types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("requests carry bearer token and parse json", async () => {
  const fetchFn = vi
    .fn()
    .mockResolvedValue(
      jsonResponse(200, { month_usd: 1.5, task_usd_limit: null, monthly_usd_limit: 10 }),
    );
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  const budget = await client.budget();
  expect(budget.month_usd).toBe(1.5);
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8686/budget");
  expect(init.headers.Authorization).toBe("Bearer tok");
});

test("list tasks builds query string from filters", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, []));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  await client.listTasks({ status: "running" });
  expect(fetchFn.mock.calls[0][0]).toBe("http://127.0.0.1:8686/tasks?status=running");
  await client.listTasks();
  expect(fetchFn.mock.calls[1][0]).toBe("http://127.0.0.1:8686/tasks");
});

test("non-2xx responses raise ApiError with detail", async () => {
  const detail = {
    error: "preflight failed",
    checks: [{ name: "input", level: "fail", message: "missing" }],
  };
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(409, { detail }));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  const error = await client.runTask("default", "t1").catch((e) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error.status).toBe(409);
  expect(error.detail).toEqual(detail);
});

test("run task sends skip_preflight body", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(202, { queued: true }));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  await client.runTask("default", "t1", { skipPreflight: true });
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8686/tasks/default/t1/run");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({ skip_preflight: true });
});

test("rerun task sends skip_preflight body", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(202, { queued: true }));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  await client.rerunTask("default", "t1", { skipPreflight: true });
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8686/tasks/default/t1/rerun");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({ skip_preflight: true });
});

test("ws url embeds token as query param", () => {
  const client = new ApiClient("http://127.0.0.1:8686", "tok");
  expect(client.wsUrl()).toBe("ws://127.0.0.1:8686/ws/events?token=tok");
});

test("listArtifacts hits the artifacts endpoint", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => [{ file: "05-translation.json", index: 5, name: "translation.json", schema_version: 1, size: 10, mtime: 1 }],
  });
  const client = new ApiClient("http://x", "tok", fetchMock as unknown as typeof fetch);
  const rows = await client.listArtifacts("p", "t1");
  expect(rows[0].file).toBe("05-translation.json");
  expect(fetchMock).toHaveBeenCalledWith("http://x/tasks/p/t1/artifacts", expect.anything());
});

test("saveArtifact PUTs the body", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ file: "06-translation.json", stages_reset: 1 }),
  });
  const client = new ApiClient("http://x", "tok", fetchMock as unknown as typeof fetch);
  const result = await client.saveArtifact("p", "t1", "translation.json", { segments: [] });
  expect(result.file).toBe("06-translation.json");
  const call = fetchMock.mock.calls[0];
  expect(call[0]).toBe("http://x/tasks/p/t1/artifacts/translation.json");
  expect(call[1].method).toBe("PUT");
});

test("renderFrame returns a blob", async () => {
  const blob = new Blob([new Uint8Array([137, 80])], { type: "image/png" });
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: async () => blob });
  const client = new ApiClient("http://x", "tok", fetchMock as unknown as typeof fetch);
  const out = await client.renderFrame("p", "t1", { style: { font_size: 48 }, text: "hi" });
  expect(out.type).toBe("image/png");
});

test("renameTask PATCHes the name", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, { id: "t1", name: "新名" }));
  const client = new ApiClient("http://x", "tok", fetchFn);
  const record = await client.renameTask("p", "t1", "新名");
  expect(record.name).toBe("新名");
  const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("http://x/tasks/p/t1");
  expect(init.method).toBe("PATCH");
  expect(JSON.parse(init.body as string)).toEqual({ name: "新名" });
});

test("config endpoints round trip", async () => {
  const doc = {
    schema_version: 1,
    default_project: "default",
    budget: { task_usd_limit: null, monthly_usd_limit: null },
    llm_providers: {},
    notifications: { channels: [] },
    discord_bot: {
      enabled: false,
      bot_token: "",
      bot_token_env: "",
      guild_id: "",
      channel_id: "",
      allowed_user_ids: [],
    },
    sync: {
      enabled: false,
      mode: "folder",
      folder_path: "",
      webdav_url: "",
      webdav_username: "",
      webdav_password: "",
      auto_interval_minutes: 0,
    },
    mcp_servers: {},
    skills: {},
    dubbing: {
      hf_token: "",
      python: "",
      inference_timesteps: null,
      cfg_value: null,
      seed: null,
      denoise: false,
      diarize_enabled: true,
    },
    pdf: { python: "" },
    audio: { diarize_enabled: true, dub_enabled: false, translate_enabled: true },
    asr: {
      engine: "faster_whisper",
      audio_engine: "",
      model: "small",
      macos_locale: "",
      cloud_base_url: "https://api.openai.com/v1",
      cloud_api_key: "",
      cloud_api_key_env: "",
      custom_base_url: "",
      custom_api_key: "",
      custom_api_key_env: "",
      custom_model: "",
      zh_prompt: true,
    },
  } as CoreConfigDoc;
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, doc));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  await client.getConfig();
  expect(fetchFn.mock.calls[0][0]).toBe("http://127.0.0.1:8686/config");
  await client.saveConfig(doc);
  const [url, init] = fetchFn.mock.calls[1];
  expect(url).toBe("http://127.0.0.1:8686/config");
  expect(init.method).toBe("PUT");
  expect(JSON.parse(init.body).default_project).toBe("default");
});

test("test notification posts channel body", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  const result = await client.testNotification({
    type: "discord",
    webhook_url: "https://discord.example/hook",
  });
  expect(result.ok).toBe(true);
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8686/config/notifications/test");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({
    channel: { type: "discord", webhook_url: "https://discord.example/hook" },
  });
});

test("pauseTask posts to the pause endpoint", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(202, { pausing: true }));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  const result = await client.pauseTask("p", "t1");
  expect(result.pausing).toBe(true);
  const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("http://127.0.0.1:8686/tasks/p/t1/pause");
  expect(init.method).toBe("POST");
});

test("getSyncStatus fetches the sync status", async () => {
  const status = {
    enabled: true,
    mode: "folder",
    syncing: false,
    last_sync: null,
    last_result: null,
    conflicts: [],
    peers: [],
  };
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, status));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  const result = await client.getSyncStatus();
  expect(result.enabled).toBe(true);
  expect(fetchFn.mock.calls[0][0]).toBe("http://127.0.0.1:8686/sync/status");
});

test("runSync posts to the run endpoint", async () => {
  const report = { ok: true, pushed: [], pulled: [], merged: [], conflicts: 0, error: null };
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, report));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  const result = await client.runSync();
  expect(result.ok).toBe(true);
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8686/sync/run");
  expect(init.method).toBe("POST");
});

test("resolveSyncConflict posts file, source and choice", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, { resolved: true }));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  await client.resolveSyncConflict("glossaries/global.csv", "term", "remote");
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8686/sync/resolve");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({
    file: "glossaries/global.csv",
    source: "term",
    choice: "remote",
  });
});

test("skills endpoints hit list, read, write, create and delete", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, {}));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  await client.listSkills();
  expect(fetchFn.mock.calls[0][0]).toBe("http://127.0.0.1:8686/skills");
  await client.getSkill("honorific-style");
  expect(fetchFn.mock.calls[1][0]).toBe("http://127.0.0.1:8686/skills/honorific-style");
  await client.putSkill("honorific-style", "---\nname: honorific-style\n---\nbody");
  const [putUrl, putInit] = fetchFn.mock.calls[2];
  expect(putUrl).toBe("http://127.0.0.1:8686/skills/honorific-style");
  expect(putInit.method).toBe("PUT");
  expect(JSON.parse(putInit.body)).toEqual({
    content: "---\nname: honorific-style\n---\nbody",
  });
  await client.createSkill("new-skill");
  const [postUrl, postInit] = fetchFn.mock.calls[3];
  expect(postUrl).toBe("http://127.0.0.1:8686/skills");
  expect(postInit.method).toBe("POST");
  expect(JSON.parse(postInit.body)).toEqual({ name: "new-skill" });
  await client.deleteSkill("new-skill");
  const [delUrl, delInit] = fetchFn.mock.calls[4];
  expect(delUrl).toBe("http://127.0.0.1:8686/skills/new-skill");
  expect(delInit.method).toBe("DELETE");
});

test("putSkill validation failure carries the errors list", async () => {
  const errors = ["frontmatter is missing a description", "body is empty"];
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(422, { detail: errors }));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  const error = await client.putSkill("x", "bad").catch((e) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error.status).toBe(422);
  expect(error.detail).toEqual(errors);
});

test("proposal endpoints build urls and filter by status", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, []));
  const client = new ApiClient("http://127.0.0.1:8686", "tok", fetchFn);
  await client.listProposals();
  expect(fetchFn.mock.calls[0][0]).toBe("http://127.0.0.1:8686/proposals");
  await client.listProposals("pending");
  expect(fetchFn.mock.calls[1][0]).toBe("http://127.0.0.1:8686/proposals?status=pending");
  await client.approveProposal("prop-1");
  const [approveUrl, approveInit] = fetchFn.mock.calls[2];
  expect(approveUrl).toBe("http://127.0.0.1:8686/proposals/prop-1/approve");
  expect(approveInit.method).toBe("POST");
  await client.rejectProposal("prop-1");
  const [rejectUrl, rejectInit] = fetchFn.mock.calls[3];
  expect(rejectUrl).toBe("http://127.0.0.1:8686/proposals/prop-1/reject");
  expect(rejectInit.method).toBe("POST");
});

test("list glossaries passes domain as query param", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, []));
  const client = new ApiClient("http://x", "tok", fetchFn);
  await client.listGlossaries("video");
  expect(fetchFn.mock.calls[0][0]).toBe("http://x/glossaries?domain=video");
  await client.listGlossaries();
  expect(fetchFn.mock.calls[1][0]).toBe("http://x/glossaries");
});

test("create glossary posts name and domain", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(201, { id: "anime-terms" }));
  const client = new ApiClient("http://x", "tok", fetchFn);
  await client.createGlossary("Anime Terms", "video");
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://x/glossaries");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({ name: "Anime Terms", domain: "video" });
});

test("import glossary posts content and format", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(201, { id: "imp", entry_count: 2 }));
  const client = new ApiClient("http://x", "tok", fetchFn);
  await client.importGlossary("Imp", "general", "csv-content", "csv");
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://x/glossaries/import");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({
    name: "Imp",
    domain: "general",
    content: "csv-content",
    format: "csv",
  });
});

test("get glossary hits the id route", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, { id: "anime", entries: [] }));
  const client = new ApiClient("http://x", "tok", fetchFn);
  await client.getGlossary("anime");
  expect(fetchFn.mock.calls[0][0]).toBe("http://x/glossaries/anime");
});

test("patch glossary sends only given fields", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, { id: "anime" }));
  const client = new ApiClient("http://x", "tok", fetchFn);
  await client.patchGlossary("anime", { enabled: false });
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://x/glossaries/anime");
  expect(init.method).toBe("PATCH");
  expect(JSON.parse(init.body)).toEqual({ enabled: false });
});

test("delete glossary hits the id route", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, { deleted: true }));
  const client = new ApiClient("http://x", "tok", fetchFn);
  await client.deleteGlossary("anime");
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://x/glossaries/anime");
  expect(init.method).toBe("DELETE");
});

test("put glossary entries sends the entries body", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, { saved: true, count: 1 }));
  const client = new ApiClient("http://x", "tok", fetchFn);
  const entries = [{ source: "Kirito", target: "桐人", notes: "", category: "人名" }];
  await client.putGlossaryEntries("anime", entries);
  const [url, init] = fetchFn.mock.calls[0];
  expect(url).toBe("http://x/glossaries/anime/entries");
  expect(init.method).toBe("PUT");
  expect(JSON.parse(init.body)).toEqual({ entries });
});

test("export glossary passes the format", async () => {
  const fetchFn = vi.fn().mockResolvedValue(jsonResponse(200, "source,target"));
  const client = new ApiClient("http://x", "tok", fetchFn);
  await client.exportGlossary("anime", "json");
  expect(fetchFn.mock.calls[0][0]).toBe("http://x/glossaries/anime/export?format=json");
});
