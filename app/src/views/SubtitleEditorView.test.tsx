import { describe, expect, test, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithConnection } from "../test/helpers";
import type { ApiClient } from "../lib/api/client";
import { SubtitleEditorView } from "./SubtitleEditorView";

function api(overrides = {}) {
  return {
    readArtifact: vi.fn(async (_p: string, _t: string, name: string): Promise<unknown> => {
      if (name === "translation.json") {
        return {
          schema_version: 1, source_language: "en", target_language: "zh",
          segments: [
            { id: 1, start: 0, end: 1, source: "hello", target: "你好" },
            { id: 2, start: 1, end: 2, source: "world", target: "世界" },
          ],
        };
      }
      return { schema_version: 1, flags: [{ id: 2, note: "確認術語", round: 1 }] };
    }) as unknown as ApiClient["readArtifact"],
    saveArtifact: vi.fn(async () => ({ file: "06-translation.json", stages_reset: 1 })),
    ...overrides,
  };
}

describe("SubtitleEditorView", () => {
  test("renders source/target rows from translation artifact", async () => {
    renderWithConnection(
      <SubtitleEditorView project="p" taskId="t1" onBack={() => {}} />,
      { api: api() },
    );
    expect(await screen.findByDisplayValue("你好")).toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  test("shows proofread flag badge on the flagged segment", async () => {
    renderWithConnection(
      <SubtitleEditorView project="p" taskId="t1" onBack={() => {}} />,
      { api: api() },
    );
    expect(await screen.findByText("確認術語")).toBeInTheDocument();
  });

  test("edit then save calls saveArtifact with edited target", async () => {
    const client = api();
    renderWithConnection(
      <SubtitleEditorView project="p" taskId="t1" onBack={() => {}} />,
      { api: client },
    );
    const field = await screen.findByDisplayValue("你好");
    await userEvent.clear(field);
    await userEvent.type(field, "哈囉");
    await userEvent.click(screen.getByText("存回"));
    await waitFor(() => expect(client.saveArtifact).toHaveBeenCalled());
    const [, , name, body] = client.saveArtifact.mock.calls[0] as unknown as [
      string,
      string,
      string,
      { segments: { target: string }[] },
    ];
    expect(name).toBe("translation.json");
    expect(body.segments[0].target).toBe("哈囉");
  });
});
