import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ApiClient } from "../lib/api/client";
import type { CoreConfigDoc } from "../lib/api/types";
import { renderWithConnection } from "../test/helpers";
import { SettingsView } from "./SettingsView";

const DEFAULT_CONFIG: CoreConfigDoc = {
  schema_version: 1,
  default_project: "default",
  budget: { task_usd_limit: null, monthly_usd_limit: null },
  llm_providers: {},
  notifications: { channels: [] },
};

function setup(overrides: Partial<ApiClient> = {}) {
  const saveConfig = vi.fn().mockImplementation((body) => Promise.resolve(body));
  const api: Partial<ApiClient> = {
    getConfig: vi.fn().mockResolvedValue(DEFAULT_CONFIG),
    saveConfig,
    ...overrides,
  };
  renderWithConnection(<SettingsView />, { api });
  return { saveConfig };
}

test("no save bar until draft differs from server config", async () => {
  setup();
  await screen.findByLabelText("預設專案");
  expect(screen.queryByText("有未儲存的變更")).not.toBeInTheDocument();
});

test("editing default project shows save bar and saves full document", async () => {
  const { saveConfig } = setup();
  const input = await screen.findByLabelText("預設專案");
  await userEvent.type(input, "-x");
  expect(screen.getByText("有未儲存的變更")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(saveConfig).toHaveBeenCalledTimes(1));
  expect(saveConfig.mock.calls[0][0].default_project).toBe("default-x");
  await screen.findByText("已儲存");
});

test("empty default project blocks save", async () => {
  setup();
  const input = await screen.findByLabelText("預設專案");
  await userEvent.clear(input);
  expect(screen.getByText("預設專案不可空白")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "儲存" })).toBeDisabled();
});

test("discard restores server values", async () => {
  setup();
  const input = await screen.findByLabelText("預設專案");
  await userEvent.type(input, "-x");
  await userEvent.click(screen.getByRole("button", { name: "放棄變更" }));
  expect(screen.getByLabelText("預設專案")).toHaveValue("default");
  expect(screen.queryByText("有未儲存的變更")).not.toBeInTheDocument();
});
