import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { BasicsSection } from "./BasicsSection";

function setup(budget = { task_usd_limit: 5, monthly_usd_limit: null }) {
  const onDefaultProject = vi.fn();
  const onBudget = vi.fn();
  const onValidity = vi.fn();
  render(
    <BasicsSection
      defaultProject="default"
      budget={budget}
      onDefaultProject={onDefaultProject}
      onBudget={onBudget}
      onValidity={onValidity}
    />,
  );
  return { onDefaultProject, onBudget, onValidity };
}

test("renders current values and unlimited as empty", () => {
  setup();
  expect(screen.getByDisplayValue("default")).toBeInTheDocument();
  expect(screen.getByLabelText("單任務上限（USD）")).toHaveValue("5");
  expect(screen.getByLabelText("每月上限（USD）")).toHaveValue("");
});

test("valid number propagates parsed budget", async () => {
  const { onBudget, onValidity } = setup();
  await userEvent.type(screen.getByLabelText("每月上限（USD）"), "30");
  expect(onValidity).toHaveBeenLastCalledWith(true);
  expect(onBudget).toHaveBeenLastCalledWith({ task_usd_limit: 5, monthly_usd_limit: 30 });
});

test("clearing a limit propagates null", async () => {
  const { onBudget } = setup();
  await userEvent.clear(screen.getByLabelText("單任務上限（USD）"));
  expect(onBudget).toHaveBeenLastCalledWith({ task_usd_limit: null, monthly_usd_limit: null });
});

test("invalid number reports invalid and keeps last budget", async () => {
  const { onBudget, onValidity } = setup();
  await userEvent.type(screen.getByLabelText("單任務上限（USD）"), "x");
  expect(onValidity).toHaveBeenLastCalledWith(false);
  expect(screen.getByText("須為不小於 0 的數字")).toBeInTheDocument();
  expect(onBudget).not.toHaveBeenCalled();
});

test("project edits propagate raw string", async () => {
  const { onDefaultProject } = setup();
  await userEvent.type(screen.getByLabelText("預設專案"), "x");
  expect(onDefaultProject).toHaveBeenLastCalledWith("defaultx");
});
