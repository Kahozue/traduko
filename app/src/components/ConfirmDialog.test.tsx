import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

function renderDialog(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      title="重新執行任務"
      body="重新執行會重跑全部階段，編輯器手改的譯文與字幕會被覆蓋。"
      confirmLabel="重新執行"
      cancelLabel="取消"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onConfirm, onCancel };
}

test("renders the title and body", () => {
  renderDialog();
  expect(screen.getByText("重新執行任務")).toBeInTheDocument();
  expect(
    screen.getByText("重新執行會重跑全部階段，編輯器手改的譯文與字幕會被覆蓋。"),
  ).toBeInTheDocument();
});

test("clicking confirm calls onConfirm", async () => {
  const { onConfirm } = renderDialog();
  await userEvent.click(screen.getByRole("button", { name: "重新執行" }));
  expect(onConfirm).toHaveBeenCalledOnce();
});

test("clicking cancel calls onCancel", async () => {
  const { onCancel } = renderDialog();
  await userEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(onCancel).toHaveBeenCalledOnce();
});

test("pressing Escape calls onCancel", async () => {
  const { onCancel } = renderDialog();
  await userEvent.keyboard("{Escape}");
  expect(onCancel).toHaveBeenCalledOnce();
});

test("confirm button is disabled while busy", () => {
  renderDialog({ busy: true });
  expect(screen.getByRole("button", { name: "重新執行" })).toBeDisabled();
});
