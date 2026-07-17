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

test("assistant button toggles a docked panel that never joins the nav's active state", async () => {
  renderWithConnection(
    <AppShell active="tasks" onNavigate={vi.fn()}>
      <p>content</p>
    </AppShell>,
    { api: { getAssistantHistory: vi.fn().mockResolvedValue([]) } },
  );
  expect(screen.queryByRole("heading", { name: "助理" })).not.toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: "助理" });
  expect(toggle).toHaveAttribute("aria-pressed", "false");

  await userEvent.click(toggle);
  const heading = await screen.findByRole("heading", { name: "助理" });
  expect(toggle).toHaveAttribute("aria-pressed", "true");

  // Flex sibling, not an overlay: the panel sits alongside <main>, sharing
  // its parent, rather than stacking on top of it.
  const panel = heading.closest("aside");
  const main = screen.getByText("content").closest("main");
  expect(panel?.parentElement).toBe(main?.parentElement);

  await userEvent.click(toggle);
  expect(screen.queryByRole("heading", { name: "助理" })).not.toBeInTheDocument();
});

test("reopening the assistant panel keeps previously loaded messages", async () => {
  const getAssistantHistory = vi
    .fn()
    .mockResolvedValue([{ role: "user", text: "hello", ts: "2026-07-18T00:00:00+00:00" }]);
  renderWithConnection(
    <AppShell active="tasks" onNavigate={vi.fn()}>
      <p>content</p>
    </AppShell>,
    { api: { getAssistantHistory } },
  );
  const toggle = screen.getByRole("button", { name: "助理" });
  await userEvent.click(toggle);
  await screen.findByText("hello");

  await userEvent.click(toggle); // close
  expect(screen.queryByText("hello")).not.toBeInTheDocument();

  await userEvent.click(toggle); // reopen
  expect(await screen.findByText("hello")).toBeInTheDocument();
  // The cache (staleTime: Infinity) is what makes the reopen instant: no
  // second fetch fires just from remounting the panel.
  expect(getAssistantHistory).toHaveBeenCalledTimes(1);
});
