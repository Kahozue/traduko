import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import type { ApiClient } from "../lib/api/client";
import type { GlossaryDetail } from "../lib/api/types";
import { renderWithConnection } from "../test/helpers";
import { GlossaryEditorView } from "./GlossaryEditorView";

const DETAIL: GlossaryDetail = {
  id: "anime-terms",
  name: "Anime Terms",
  domain: "video",
  enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  entries: [
    { source: "Kirito", target: "桐人", notes: "protagonist", category: "人名" },
    { source: "Asuna", target: "亞絲娜", notes: "", category: "人名" },
    { source: "Aincrad", target: "艾恩葛朗特", notes: "", category: "地名" },
  ],
};

function setup(overrides: Partial<ApiClient> = {}, onBack: () => void = () => {}) {
  const api: Partial<ApiClient> = {
    getGlossary: vi.fn().mockResolvedValue(DETAIL),
    putGlossaryEntries: vi.fn().mockResolvedValue({ saved: true, count: 3 }),
    patchGlossary: vi.fn().mockResolvedValue({ ...DETAIL, name: "Renamed" }),
    exportGlossary: vi.fn().mockResolvedValue("source,target,notes,category\n"),
    ...overrides,
  };
  renderWithConnection(<GlossaryEditorView glossaryId="anime-terms" onBack={onBack} />, {
    api,
  });
  return api;
}

async function loaded() {
  return await screen.findByDisplayValue("桐人");
}

describe("GlossaryEditorView", () => {
  test("loads entries grouped by category", async () => {
    setup();
    await loaded();
    expect(screen.getByDisplayValue("桐人")).toBeInTheDocument();
    expect(screen.getByDisplayValue("艾恩葛朗特")).toBeInTheDocument();
    expect(screen.getByText("人名")).toBeInTheDocument();
    expect(screen.getByText("地名")).toBeInTheDocument();
  });

  test("editing a target then saving PUTs the entries", async () => {
    const api = setup();
    const field = await loaded();
    fireEvent.change(field, { target: { value: "キリト" } });
    expect(screen.getByText("有未儲存的變更")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() =>
      expect(api.putGlossaryEntries).toHaveBeenCalledWith(
        "anime-terms",
        expect.arrayContaining([
          expect.objectContaining({ source: "Kirito", target: "キリト" }),
        ]),
      ),
    );
  });

  test("search filters the rows", async () => {
    setup();
    await loaded();
    await userEvent.type(screen.getByRole("searchbox", { name: "搜尋" }), "桐人");
    // The search box itself also holds the query; only the target cell row
    // remains, the other category's rows are filtered out.
    expect(screen.getAllByDisplayValue("桐人")).toHaveLength(2);
    expect(screen.queryByDisplayValue("艾恩葛朗特")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("亞絲娜")).not.toBeInTheDocument();
  });

  test("selecting and batch-deleting removes the rows and saves", async () => {
    const api = setup();
    await loaded();
    await userEvent.click(screen.getByRole("checkbox", { name: /選取 Kirito/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /選取 Asuna/ }));
    await userEvent.click(screen.getByRole("button", { name: /刪除所選/ }));
    expect(screen.queryByDisplayValue("桐人")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() =>
      expect(api.putGlossaryEntries).toHaveBeenCalledWith(
        "anime-terms",
        [
          expect.objectContaining({ source: "Aincrad" }),
        ],
      ),
    );
  });

  test("renaming the table PATCHes the name", async () => {
    const api = setup();
    await loaded();
    const nameField = screen.getByLabelText("名詞表名稱");
    fireEvent.change(nameField, { target: { value: "Renamed" } });
    await userEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() =>
      expect(api.patchGlossary).toHaveBeenCalledWith("anime-terms", { name: "Renamed" }),
    );
  });

  test("collapsing a category hides its rows", async () => {
    setup();
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: /人名/ }));
    expect(screen.queryByDisplayValue("桐人")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("艾恩葛朗特")).toBeInTheDocument();
  });

  test("adding a row appends it to the uncategorized group", async () => {
    setup();
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "新增列" }));
    const sources = screen.getAllByPlaceholderText("原文");
    expect(sources).toHaveLength(4);
  });

  test("export fetches the table content", async () => {
    const api = setup();
    const createSpy = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", { ...URL, createObjectURL: createSpy, revokeObjectURL: vi.fn() });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "匯出" }));
    await waitFor(() =>
      expect(api.exportGlossary).toHaveBeenCalledWith("anime-terms", "csv"),
    );
    clickSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  test("back with unsaved edits asks to discard", async () => {
    const onBack = vi.fn();
    setup({}, onBack);
    const field = await loaded();
    fireEvent.change(field, { target: { value: "キリト" } });
    await userEvent.click(screen.getByRole("button", { name: "返回" }));
    expect(onBack).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "放棄修改" }));
    expect(onBack).toHaveBeenCalled();
  });
});
