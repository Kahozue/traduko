import { describe, expect, test, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithConnection } from "../test/helpers";
import type { ApiClient } from "../lib/api/client";
import { DocumentEditorView } from "./DocumentEditorView";

const DOCUMENT = {
  schema_version: 1,
  format: "epub",
  chapters: [
    {
      id: "ch-0001",
      title: "第一章",
      href: "ch1.xhtml",
      blocks: [
        { id: "b-1", kind: "paragraph", translate: true, text: "Hello.", anchor: "3" },
        { id: "b-2", kind: "paragraph", translate: true, text: "World.", anchor: "4" },
      ],
    },
    {
      id: "ch-0002",
      title: "第二章",
      href: "ch2.xhtml",
      blocks: [
        { id: "b-3", kind: "paragraph", translate: true, text: "Again.", anchor: "3" },
      ],
    },
  ],
};

const CHUNKS = {
  schema_version: 1,
  chunks: [
    { id: "c-0001", chapter_id: "ch-0001", block_ids: ["b-1", "b-2"], char_count: 12 },
    { id: "c-0002", chapter_id: "ch-0002", block_ids: ["b-3"], char_count: 6 },
  ],
};

const TRANSLATION = {
  schema_version: 1,
  chunks: [
    {
      id: "c-0001",
      status: "translated",
      blocks: [
        { id: "b-1", text: "你好。" },
        { id: "b-2", text: "世界。" },
      ],
    },
    { id: "c-0002", status: "failed", blocks: [] },
  ],
};

const QC = {
  schema_version: 1,
  flags: [
    { chunk_id: "c-0001", block_id: "b-2", type: "untranslated", evidence: "same text" },
    { chunk_id: "c-0002", block_id: "", type: "echo", evidence: "chunk echoes source" },
  ],
};

function api(overrides = {}) {
  return {
    readArtifact: vi.fn(async (_p: string, _t: string, name: string): Promise<unknown> => {
      if (name === "document.json") return DOCUMENT;
      if (name === "chunks.json") return CHUNKS;
      if (name === "translation.json") return TRANSLATION;
      if (name === "qc.json") return QC;
      throw new Error(`unexpected artifact ${name}`);
    }) as unknown as ApiClient["readArtifact"],
    saveArtifact: vi.fn(async () => ({ file: "05-translation.json", stages_reset: 2 })),
    ...overrides,
  };
}

function render(onBack: () => void = () => {}, client = api()) {
  renderWithConnection(
    <DocumentEditorView project="p" taskId="t1" onBack={onBack} />,
    { api: client },
  );
  return client;
}

async function activateRow(text: string) {
  await userEvent.click(await screen.findByText(text));
  return screen.getByRole("textbox", { name: "譯文" });
}

describe("DocumentEditorView", () => {
  test("renders block rows as text without textareas", async () => {
    render();
    expect(await screen.findByText("你好。")).toBeInTheDocument();
    expect(screen.getByText("Hello.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "譯文" })).not.toBeInTheDocument();
  });

  test("shows chapter separators when the document has several chapters", async () => {
    render();
    expect(await screen.findByText("第一章")).toBeInTheDocument();
    expect(screen.getByText("第二章")).toBeInTheDocument();
  });

  test("failed chunk blocks render with empty target", async () => {
    render();
    await screen.findByText("你好。");
    const row = screen.getByText("Again.").closest("[data-block-id]");
    expect(row).not.toBeNull();
  });

  test("block-level qc flag shows evidence; chunk-level flag lands on first block", async () => {
    render();
    expect(await screen.findByText("same text")).toBeInTheDocument();
    expect(screen.getByText("回聲")).toBeInTheDocument();
    expect(screen.getByText("未翻譯")).toBeInTheDocument();
  });

  test("clicking a row opens the editor; Enter moves to next row", async () => {
    render();
    const field = await activateRow("你好。");
    expect(field).toHaveDisplayValue("你好。");
    await userEvent.type(field, "{Enter}");
    expect(screen.getByRole("textbox", { name: "譯文" })).toHaveDisplayValue("世界。");
  });

  test("Escape closes the editor keeping edits", async () => {
    render();
    const field = await activateRow("你好。");
    await userEvent.clear(field);
    await userEvent.type(field, "哈囉。");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "譯文" })).not.toBeInTheDocument();
    expect(screen.getByText("哈囉。")).toBeInTheDocument();
  });

  test("save rebuilds chunks and flips a completed chunk to translated", async () => {
    const client = render();
    const field = await activateRow("你好。");
    await userEvent.clear(field);
    await userEvent.type(field, "哈囉。");
    await userEvent.keyboard("{Escape}");
    // Fill in the failed chunk's block so it becomes translated.
    await userEvent.click(screen.getByText("Again."));
    const again = screen.getByRole("textbox", { name: "譯文" });
    await userEvent.type(again, "再次。");
    await userEvent.click(screen.getByText("存回"));
    await waitFor(() => expect(client.saveArtifact).toHaveBeenCalled());
    const [, , name, body] = client.saveArtifact.mock.calls[0] as unknown as [
      string,
      string,
      string,
      { chunks: { id: string; status: string; blocks: { id: string; text: string }[] }[] },
    ];
    expect(name).toBe("translation.json");
    expect(body.chunks[0].blocks[0].text).toBe("哈囉。");
    expect(body.chunks[0].status).toBe("translated");
    expect(body.chunks[1].status).toBe("translated");
    expect(body.chunks[1].blocks).toEqual([{ id: "b-3", text: "再次。" }]);
  });

  test("save keeps failed status when a chunk still has empty targets", async () => {
    const client = render();
    const field = await activateRow("你好。");
    await userEvent.type(field, "！");
    await userEvent.click(screen.getByText("存回"));
    await waitFor(() => expect(client.saveArtifact).toHaveBeenCalled());
    const [, , , body] = client.saveArtifact.mock.calls[0] as unknown as [
      string, string, string, { chunks: { id: string; status: string }[] },
    ];
    expect(body.chunks[1].status).toBe("failed");
  });

  test("Cmd+S saves when dirty", async () => {
    const client = render();
    const field = await activateRow("你好。");
    await userEvent.type(field, "！");
    await userEvent.keyboard("{Meta>}s{/Meta}");
    await waitFor(() => expect(client.saveArtifact).toHaveBeenCalled());
  });

  test("search filters rows by source and target", async () => {
    render();
    await screen.findByText("你好。");
    await userEvent.type(screen.getByRole("searchbox", { name: "搜尋" }), "World");
    expect(screen.queryByText("你好。")).not.toBeInTheDocument();
    expect(screen.getByText("世界。")).toBeInTheDocument();
  });

  test("replace all rewrites targets of matching rows", async () => {
    render();
    await screen.findByText("你好。");
    await userEvent.type(screen.getByRole("searchbox", { name: "搜尋" }), "世界");
    await userEvent.type(screen.getByRole("textbox", { name: "取代為" }), "地球");
    await userEvent.click(screen.getByText("取代全部"));
    await userEvent.clear(screen.getByRole("searchbox", { name: "搜尋" }));
    expect(screen.getByText("地球。")).toBeInTheDocument();
  });

  test("flagged-only toggle hides unflagged rows", async () => {
    render();
    await screen.findByText("你好。");
    await userEvent.click(screen.getByLabelText("只看標註"));
    expect(screen.queryByText("你好。")).not.toBeInTheDocument();
    expect(screen.getByText("世界。")).toBeInTheDocument();
    expect(screen.getByText("Again.")).toBeInTheDocument();
  });

  test("next-flag button activates the first flagged row", async () => {
    render();
    await screen.findByText("你好。");
    await userEvent.click(screen.getByRole("button", { name: "下一個標註" }));
    expect(screen.getByRole("textbox", { name: "譯文" })).toHaveDisplayValue("世界。");
  });

  test("missing qc artifact renders without flags", async () => {
    const client = api({
      readArtifact: vi.fn(async (_p: string, _t: string, name: string): Promise<unknown> => {
        if (name === "document.json") return DOCUMENT;
        if (name === "chunks.json") return CHUNKS;
        if (name === "translation.json") return TRANSLATION;
        throw new Error("no qc yet");
      }) as unknown as ApiClient["readArtifact"],
    });
    render(() => {}, client);
    expect(await screen.findByText("你好。")).toBeInTheDocument();
    expect(screen.queryByText("回聲")).not.toBeInTheDocument();
  });

  test("back with unsaved edits asks for confirmation", async () => {
    const onBack = vi.fn();
    render(onBack);
    const field = await activateRow("你好。");
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
    await screen.findByText("你好。");
    await userEvent.click(screen.getByText("返回任務"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
