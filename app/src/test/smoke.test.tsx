import { render } from "@testing-library/react";
import { test, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi
    .fn()
    .mockResolvedValue({ baseUrl: "http://127.0.0.1:8686", token: null, dataRoot: "/tmp" }),
}));

import App from "../App";

test("app renders without crashing", () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<App />);
});
