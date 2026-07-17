import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ApiClient } from "../lib/api/client";
import type { CoreConfigDoc } from "../lib/api/types";
import { themeStore } from "../lib/theme";
import { renderWithConnection } from "../test/helpers";
import { SettingsView } from "./SettingsView";

const DEFAULT_CONFIG: CoreConfigDoc = {
  schema_version: 1,
  default_project: "default",
  budget: { task_usd_limit: null, monthly_usd_limit: null },
  llm_providers: {},
  notifications: { channels: [] },
  discord_bot: {
    enabled: false,
    bot_token: "",
    bot_token_env: "",
    guild_id: "",
    channel_id: "",
    allowed_user_ids: [],
  },
  sync: {
    enabled: false,
    mode: "folder",
    folder_path: "",
    webdav_url: "",
    webdav_username: "",
    webdav_password: "",
    auto_interval_minutes: 0,
  },
};

function setup(overrides: Partial<ApiClient> = {}) {
  const saveConfig = vi.fn().mockImplementation((body) => Promise.resolve(body));
  const api: Partial<ApiClient> = {
    getConfig: vi.fn().mockResolvedValue(DEFAULT_CONFIG),
    getSyncStatus: vi.fn().mockResolvedValue({
      enabled: false,
      mode: "folder",
      syncing: false,
      last_sync: null,
      last_result: null,
      conflicts: [],
      peers: [],
    }),
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

test("tabs render in order and default to the general tab", async () => {
  setup();
  await screen.findByLabelText("預設專案");
  const tabs = screen.getAllByRole("tab");
  expect(tabs.map((el) => el.textContent)).toEqual(["一般", "影片", "整合", "關於"]);
  expect(screen.getByRole("tab", { name: "一般" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByText("語音辨識")).not.toBeVisible();
});

test("switching to the video tab reveals the ASR section", async () => {
  setup();
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "影片" }));
  expect(screen.getByText("語音辨識")).toBeVisible();
  expect(screen.getByLabelText("預設專案")).not.toBeVisible();
});

test("switching tabs keeps unsaved edits and the save bar", async () => {
  setup();
  const input = await screen.findByLabelText("預設專案");
  await userEvent.type(input, "-x");
  await userEvent.click(screen.getByRole("tab", { name: "整合" }));
  expect(screen.getByText("有未儲存的變更")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "一般" }));
  expect(screen.getByLabelText("預設專案")).toHaveValue("default-x");
});

test("save bar names the tab holding invalid fields", async () => {
  setup();
  const input = await screen.findByLabelText("預設專案");
  await userEvent.clear(input);
  await userEvent.click(screen.getByRole("tab", { name: "整合" }));
  expect(screen.getByText("有欄位未通過驗證：一般")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "儲存" })).toBeDisabled();
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

test("bot section edits mark the draft dirty", async () => {
  setup();
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "整合" }));
  await userEvent.click(screen.getByLabelText("啟用 Discord bot"));
  expect(screen.getByText("有未儲存的變更")).toBeInTheDocument();
});

test("sync now triggers a sync run", async () => {
  const runSync = vi.fn().mockResolvedValue({
    ok: true,
    pushed: [],
    pulled: [],
    merged: [],
    conflicts: 0,
    error: null,
  });
  const getSyncStatus = vi.fn().mockResolvedValue({
    enabled: true,
    mode: "folder",
    syncing: false,
    last_sync: null,
    last_result: null,
    conflicts: [],
    peers: [],
  });
  setup({ runSync, getSyncStatus });
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "整合" }));
  await userEvent.click(await screen.findByRole("button", { name: "立即同步" }));
  await waitFor(() => expect(runSync).toHaveBeenCalled());
});

test("config from an older core without a sync section does not crash", async () => {
  const legacy = { ...DEFAULT_CONFIG } as Record<string, unknown>;
  delete legacy.sync;
  delete legacy.discord_bot;
  setup({ getConfig: vi.fn().mockResolvedValue(legacy) });
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "整合" }));
  // Reaching the sync section's control proves normalize backfilled it
  // instead of throwing on draft.sync.mode.
  expect(await screen.findByLabelText("同步方式")).toBeInTheDocument();
});

test("theme choice applies instantly and never dirties the config draft", async () => {
  themeStore.setMode("system");
  setup();
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("radio", { name: "深色" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(screen.queryByText("有未儲存的變更")).not.toBeInTheDocument();
  themeStore.setMode("system");
});
