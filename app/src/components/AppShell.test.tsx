import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { renderWithConnection } from "../test/helpers";
import { AppShell } from "./AppShell";

test("renders nav and reports navigation", async () => {
  const onNavigate = vi.fn();
  renderWithConnection(
    <AppShell active="tasks" onNavigate={onNavigate}>
      <p>content</p>
    </AppShell>,
    { api: {} },
  );
  expect(screen.getByText("任務")).toBeInTheDocument();
  expect(screen.getByText("content")).toBeInTheDocument();
  await userEvent.click(screen.getByText("預算"));
  expect(onNavigate).toHaveBeenCalledWith("budget");
});
