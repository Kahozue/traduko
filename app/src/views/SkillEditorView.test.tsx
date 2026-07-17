import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { ApiError, type ApiClient } from "../lib/api/client";
import { renderWithConnection } from "../test/helpers";
import { SkillEditorView } from "./SkillEditorView";

const CONTENT = "---\nname: honorific-style\ndescription: 稱謂規則\n---\n\n以敬語翻譯。";

function setup(overrides: Partial<ApiClient> = {}, onBack: () => void = () => {}) {
  const api: Partial<ApiClient> = {
    getSkill: vi.fn().mockResolvedValue({ name: "honorific-style", content: CONTENT }),
    putSkill: vi.fn().mockResolvedValue({ saved: true }),
    ...overrides,
  };
  renderWithConnection(<SkillEditorView skill="honorific-style" onBack={onBack} />, {
    api,
  });
  return api;
}

async function editor() {
  return await screen.findByRole("textbox", { name: "Skill 編輯器" });
}

describe("SkillEditorView", () => {
  test("loads the SKILL.md into the editor", async () => {
    setup();
    expect(await editor()).toHaveDisplayValue(CONTENT);
    expect(screen.getByText("honorific-style")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "儲存" })).toBeDisabled();
  });

  test("editing marks dirty and save PUTs the new content", async () => {
    const api = setup();
    const field = await editor();
    await userEvent.type(field, "x");
    expect(screen.getByText("有未儲存的變更")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "儲存" }));
    await waitFor(() =>
      expect(api.putSkill).toHaveBeenCalledWith("honorific-style", `${CONTENT}x`),
    );
    expect(await screen.findByText("已儲存")).toBeInTheDocument();
    expect(screen.queryByText("有未儲存的變更")).not.toBeInTheDocument();
  });

  test("a 422 lists every validation error", async () => {
    const errors = ["frontmatter is missing a description", "body is empty"];
    setup({ putSkill: vi.fn().mockRejectedValue(new ApiError(422, errors)) });
    await userEvent.type(await editor(), "x");
    await userEvent.click(screen.getByRole("button", { name: "儲存" }));
    expect(await screen.findByText("內容未通過驗證：")).toBeInTheDocument();
    expect(screen.getByText("frontmatter is missing a description")).toBeInTheDocument();
    expect(screen.getByText("body is empty")).toBeInTheDocument();
    // Still dirty: the user can fix and retry.
    expect(screen.getByText("有未儲存的變更")).toBeInTheDocument();
  });

  test("a non-422 failure shows the generic message", async () => {
    setup({ putSkill: vi.fn().mockRejectedValue(new ApiError(503, "down")) });
    await userEvent.type(await editor(), "x");
    await userEvent.click(screen.getByRole("button", { name: "儲存" }));
    expect(await screen.findByText("儲存失敗")).toBeInTheDocument();
  });

  test("back without edits returns immediately", async () => {
    const onBack = vi.fn();
    setup({}, onBack);
    await editor();
    await userEvent.click(screen.getByRole("button", { name: "返回設定" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  test("back with unsaved edits asks before discarding", async () => {
    const onBack = vi.fn();
    setup({}, onBack);
    await userEvent.type(await editor(), "x");
    await userEvent.click(screen.getByRole("button", { name: "返回設定" }));
    expect(onBack).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "放棄未儲存的變更？" });
    fireEvent.click(screen.getByText("留下"));
    expect(dialog).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "返回設定" }));
    fireEvent.click(screen.getByText("放棄修改"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  test("unknown skill shows the load failure state", async () => {
    setup({
      getSkill: vi.fn().mockRejectedValue(new ApiError(404, "skill not found: x")),
    });
    expect(
      await screen.findByText("無法載入此 skill，可能已被刪除。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Skill 編輯器" }),
    ).not.toBeInTheDocument();
  });
});
