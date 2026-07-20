import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ApiError, type ApiClient } from "../../lib/api/client";
import type { GlossaryTable } from "../../lib/api/types";
import { renderWithConnection } from "../../test/helpers";
import { GlossarySection } from "./GlossarySection";

const TABLE: GlossaryTable = {
  id: "anime-terms",
  name: "Anime Terms",
  domain: "video",
  enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  entry_count: 3,
};

function setup({
  tables = [TABLE],
  api: apiOverrides = {},
}: {
  tables?: GlossaryTable[];
  api?: Partial<ApiClient>;
} = {}) {
  const onEditGlossary = vi.fn();
  const api: Partial<ApiClient> = {
    listGlossaries: vi.fn().mockResolvedValue(tables),
    createGlossary: vi.fn().mockResolvedValue({ ...TABLE, id: "new", name: "New", entry_count: 0 }),
    importGlossary: vi.fn().mockResolvedValue({ ...TABLE, id: "imp", entry_count: 2 }),
    patchGlossary: vi.fn().mockResolvedValue({ ...TABLE, enabled: false }),
    deleteGlossary: vi.fn().mockResolvedValue({ deleted: true }),
    exportGlossary: vi.fn().mockResolvedValue("source,target,notes,category\n"),
    ...apiOverrides,
  };
  renderWithConnection(
    <GlossarySection domain="video" onEditGlossary={onEditGlossary} />,
    { api },
  );
  return { onEditGlossary, api };
}

test("renders tables with name, entry count and enabled state", async () => {
  setup();
  expect(await screen.findByText("Anime Terms")).toBeInTheDocument();
  expect(screen.getByText("3 筆")).toBeInTheDocument();
  const toggle = screen.getByRole("checkbox", { name: /啟用 Anime Terms/ });
  expect(toggle).toBeChecked();
});

test("toggling enabled patches the glossary", async () => {
  const { api } = setup();
  const toggle = await screen.findByRole("checkbox", { name: /啟用 Anime Terms/ });
  await userEvent.click(toggle);
  await waitFor(() =>
    expect(api.patchGlossary).toHaveBeenCalledWith("anime-terms", { enabled: false }),
  );
});

test("creating a glossary posts the name with the section domain", async () => {
  const { api } = setup();
  await userEvent.click(await screen.findByRole("button", { name: "新增" }));
  await userEvent.type(screen.getByLabelText("名詞表名稱"), "My Terms");
  await userEvent.click(screen.getByRole("button", { name: "確認新增" }));
  await waitFor(() =>
    expect(api.createGlossary).toHaveBeenCalledWith("My Terms", "video"),
  );
});

test("importing a file reads its content and posts it", async () => {
  const { api } = setup();
  const file = new File(["source,target,notes,category\nA,B,,"], "terms.csv", {
    type: "text/csv",
  });
  const input = (await screen.findByLabelText("匯入名詞表檔案")) as HTMLInputElement;
  await userEvent.upload(input, file);
  await waitFor(() =>
    expect(api.importGlossary).toHaveBeenCalledWith(
      "terms",
      "video",
      "source,target,notes,category\nA,B,,",
      "csv",
    ),
  );
});

test("clicking a table name opens the editor", async () => {
  const { onEditGlossary } = setup();
  await userEvent.click(await screen.findByRole("button", { name: "Anime Terms" }));
  expect(onEditGlossary).toHaveBeenCalledWith("anime-terms");
});

test("exporting fetches the table content for download", async () => {
  const { api } = setup();
  const createSpy = vi.fn(() => "blob:x");
  const revokeSpy = vi.fn();
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: createSpy,
    revokeObjectURL: revokeSpy,
  });
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("Anime Terms.csv");
    });
  await userEvent.click(await screen.findByRole("button", { name: "匯出 CSV" }));
  await waitFor(() =>
    expect(api.exportGlossary).toHaveBeenCalledWith("anime-terms", "csv"),
  );
  await waitFor(() => expect(createSpy).toHaveBeenCalled());
  expect(clickSpy).toHaveBeenCalled();
  expect(revokeSpy).toHaveBeenCalled();
  clickSpy.mockRestore();
  vi.unstubAllGlobals();
});

test("empty state shows when there are no tables", async () => {
  setup({ tables: [] });
  expect(await screen.findByText("尚無名詞表")).toBeInTheDocument();
});

// --- error feedback and skipped rows (v3_5-11 M4) ---------------------------

test("a failed import shows an error row instead of nothing happening", async () => {
  setup({
    api: {
      importGlossary: vi
        .fn()
        .mockRejectedValue(new ApiError(422, "unsupported glossary format: xml")),
    },
  });
  const file = new File(["{not json"], "terms.json", { type: "application/json" });
  const input = (await screen.findByLabelText("匯入名詞表檔案")) as HTMLInputElement;
  await userEvent.upload(input, file);
  expect(await screen.findByRole("alert")).toHaveTextContent("匯入失敗");
});

test("a failed delete shows the humanized reason", async () => {
  setup({
    api: {
      deleteGlossary: vi.fn().mockRejectedValue(new ApiError(500, "disk space exhausted")),
    },
  });
  await userEvent.click(await screen.findByRole("button", { name: "移除" }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "刪除" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("磁碟空間不足");
});

test("an import with skipped rows reports how many and which", async () => {
  setup({
    api: {
      importGlossary: vi.fn().mockResolvedValue({
        ...TABLE,
        id: "imp",
        entry_count: 1,
        skipped: ["row 3: missing source", "row 4: missing target"],
      }),
    },
  });
  const file = new File(["source,target\nA,B\n,C\nD,\n"], "terms.csv", {
    type: "text/csv",
  });
  const input = (await screen.findByLabelText("匯入名詞表檔案")) as HTMLInputElement;
  await userEvent.upload(input, file);
  const notice = await screen.findByRole("status");
  expect(notice).toHaveTextContent("已略過 2 列");
  expect(notice).toHaveTextContent("row 3: missing source");
});

test("a clean import reports no skipped rows", async () => {
  setup({
    api: {
      importGlossary: vi
        .fn()
        .mockResolvedValue({ ...TABLE, id: "imp", entry_count: 2, skipped: [] }),
    },
  });
  const file = new File(["source,target\nA,B\n"], "terms.csv", { type: "text/csv" });
  const input = (await screen.findByLabelText("匯入名詞表檔案")) as HTMLInputElement;
  await userEvent.upload(input, file);
  await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
});

// --- L4: export naming, JSON export, delete confirmation --------------------

test("export uses the table name for the download, not its slug", async () => {
  const { api } = setup();
  const createSpy = vi.fn(() => "blob:x");
  vi.stubGlobal("URL", { ...URL, createObjectURL: createSpy, revokeObjectURL: vi.fn() });
  const names: string[] = [];
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
  await userEvent.click(await screen.findByRole("button", { name: "匯出 CSV" }));
  await waitFor(() => expect(api.exportGlossary).toHaveBeenCalledWith("anime-terms", "csv"));
  expect(names[0]).toBe("Anime Terms.csv");
  clickSpy.mockRestore();
  vi.unstubAllGlobals();
});

test("a table can also be exported as JSON", async () => {
  const { api } = setup();
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:x"),
    revokeObjectURL: vi.fn(),
  });
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  await userEvent.click(await screen.findByRole("button", { name: "匯出 JSON" }));
  await waitFor(() =>
    expect(api.exportGlossary).toHaveBeenCalledWith("anime-terms", "json"),
  );
  clickSpy.mockRestore();
  vi.unstubAllGlobals();
});

test("deleting a table asks first and only deletes on confirm", async () => {
  const { api } = setup();
  await userEvent.click(await screen.findByRole("button", { name: "移除" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("Anime Terms");
  await userEvent.click(within(dialog).getByRole("button", { name: "取消" }));
  expect(api.deleteGlossary).not.toHaveBeenCalled();

  await userEvent.click(screen.getByRole("button", { name: "移除" }));
  const again = await screen.findByRole("dialog");
  await userEvent.click(within(again).getByRole("button", { name: "刪除" }));
  await waitFor(() => expect(api.deleteGlossary).toHaveBeenCalledWith("anime-terms"));
});
