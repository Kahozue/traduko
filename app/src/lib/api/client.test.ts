import { expect, test, vi } from "vitest";
import { ApiClient, ApiError } from "./client";

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
