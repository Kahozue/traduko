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
