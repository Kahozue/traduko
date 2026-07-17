import { describe, expect, test, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
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
            { id: 3, start: 2, end: 3, source: "again", target: "再見" },
          ],
        };
      }
      return { schema_version: 1, flags: [{ id: 2, note: "確認術語", round: 1 }] };
    }) as unknown as ApiClient["readArtifact"],
    saveArtifact: vi.fn(async () => ({ file: "06-translation.json", stages_reset: 1 })),
    ...overrides,
  };
}

function render(onBack: () => void = () => {}, client = api()) {
  renderWithConnection(
    <SubtitleEditorView project="p" taskId="t1" onBack={onBack} />,
    { api: client },
  );
  return client;
}

async function activateRow(target: string) {
  await userEvent.click(await screen.findByText(target));
  return screen.getByRole("textbox", { name: "譯文" });
}

describe("SubtitleEditorView", () => {
  test("renders rows as text without textareas", async () => {
    render();
    expect(await screen.findByText("你好")).toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "譯文" })).not.toBeInTheDocument();
  });

  test("shows proofread flag note on the flagged segment", async () => {
    render();
    expect(await screen.findByText("確認術語")).toBeInTheDocument();
  });

  test("clicking a row opens the editor; Enter commits and moves to next row", async () => {
    render();
    const field = await activateRow("你好");
    expect(field).toHaveDisplayValue("你好");
    await userEvent.type(field, "{Enter}");
    expect(screen.getByRole("textbox", { name: "譯文" })).toHaveDisplayValue("世界");
  });

  test("Escape closes the editor keeping edits", async () => {
    render();
    const field = await activateRow("你好");
    await userEvent.clear(field);
    await userEvent.type(field, "哈囉");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "譯文" })).not.toBeInTheDocument();
    expect(screen.getByText("哈囉")).toBeInTheDocument();
  });

  test("edit then save calls saveArtifact with edited target", async () => {
    const client = render();
    const field = await activateRow("你好");
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

  test("Cmd+S saves when dirty", async () => {
    const client = render();
    const field = await activateRow("你好");
    await userEvent.type(field, "！");
    await userEvent.keyboard("{Meta>}s{/Meta}");
    await waitFor(() => expect(client.saveArtifact).toHaveBeenCalled());
  });

  test("search filters rows by source and target", async () => {
    render();
    await screen.findByText("你好");
    await userEvent.type(screen.getByRole("searchbox", { name: "搜尋" }), "world");
    expect(screen.queryByText("你好")).not.toBeInTheDocument();
    expect(screen.getByText("世界")).toBeInTheDocument();
  });

  test("replace all rewrites targets of matching rows and enables save", async () => {
    const client = render();
    await screen.findByText("你好");
    await userEvent.type(screen.getByRole("searchbox", { name: "搜尋" }), "好");
    await userEvent.type(screen.getByRole("textbox", { name: "取代為" }), "棒");
    await userEvent.click(screen.getByText("取代全部"));
    await userEvent.clear(screen.getByRole("searchbox", { name: "搜尋" }));
    expect(screen.getByText("你棒")).toBeInTheDocument();
    await userEvent.click(screen.getByText("存回"));
    await waitFor(() => expect(client.saveArtifact).toHaveBeenCalled());
    const [, , , body] = client.saveArtifact.mock.calls[0] as unknown as [
      string, string, string, { segments: { target: string }[] },
    ];
    expect(body.segments[0].target).toBe("你棒");
    expect(body.segments[1].target).toBe("世界");
  });

  test("flagged-only toggle hides unflagged rows", async () => {
    render();
    await screen.findByText("你好");
    await userEvent.click(screen.getByLabelText("只看標註"));
    expect(screen.queryByText("你好")).not.toBeInTheDocument();
    expect(screen.getByText("世界")).toBeInTheDocument();
  });

  test("next-flag button activates the flagged row", async () => {
    render();
    await screen.findByText("你好");
    await userEvent.click(screen.getByRole("button", { name: "下一個標註" }));
    expect(screen.getByRole("textbox", { name: "譯文" })).toHaveDisplayValue("世界");
  });

  test("back with unsaved edits asks for confirmation", async () => {
    const onBack = vi.fn();
    render(onBack);
    const field = await activateRow("你好");
    await userEvent.type(field, "！");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByText("返回任務"));
    expect(onBack).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    fireEvent.click(screen.getByText("留下"));
    expect(dialog).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("返回任務"));
    fireEvent.click(screen.getByText("放棄修改"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  test("back without edits leaves immediately", async () => {
    const onBack = vi.fn();
    render(onBack);
    await screen.findByText("你好");
    await userEvent.click(screen.getByText("返回任務"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
