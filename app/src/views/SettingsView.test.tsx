import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
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
  mcp_servers: {},
  skills: {},
  dubbing: { hf_token: "", python: "" },
  pdf: { python: "" },
};

function setup(
  overrides: Partial<ApiClient> = {},
  props: ComponentProps<typeof SettingsView> = {},
) {
  const saveConfig = vi.fn().mockImplementation((body) => Promise.resolve(body));
  const reloadMcp = vi.fn().mockResolvedValue([]);
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
    getMcpStatus: vi.fn().mockResolvedValue([]),
    listSkills: vi.fn().mockResolvedValue([]),
    getSkill: vi.fn().mockResolvedValue({ name: "x", content: "content" }),
    reloadMcp,
    saveConfig,
    ...overrides,
  };
  renderWithConnection(<SettingsView {...props} />, { api });
  return { saveConfig, reloadMcp };
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
  expect(tabs.map((el) => el.textContent)).toEqual([
    "一般",
    "影片",
    "文件",
    "Agent",
    "整合",
    "關於",
  ]);
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

test("the saved note dismisses itself after a moment", async () => {
  setup();
  const input = await screen.findByLabelText("預設專案");
  await userEvent.type(input, "-x");
  await userEvent.click(screen.getByRole("button", { name: "儲存" }));
  await screen.findByText("已儲存");
  await waitFor(
    () => expect(screen.queryByText("已儲存")).not.toBeInTheDocument(),
    { timeout: 4000 },
  );
}, 10000);

test("saving reconnects mcp servers", async () => {
  const { reloadMcp } = setup();
  const input = await screen.findByLabelText("預設專案");
  await userEvent.type(input, "-x");
  await userEvent.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(reloadMcp).toHaveBeenCalledTimes(1));
});

test("agent tab lists mcp servers with status", async () => {
  setup({
    getConfig: vi.fn().mockResolvedValue({
      ...DEFAULT_CONFIG,
      mcp_servers: {
        files: {
          transport: "stdio", command: "uvx", args: [], env: {},
          url: "", auth_token: "", enabled: true, confirmed: true,
        },
      },
    }),
    getMcpStatus: vi.fn().mockResolvedValue([
      {
        name: "files", transport: "stdio", enabled: true, confirmed: true,
        state: "connected", error: "",
        tools: [{ name: "read", description: "Read a file" }],
      },
    ]),
  });
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "Agent" }));
  expect(await screen.findByDisplayValue("files")).toBeVisible();
  expect(screen.getByText("已連線 · 1 個工具")).toBeVisible();
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

test("v2-04 config without confirmed fields or skills does not read as dirty", async () => {
  const legacy = {
    ...DEFAULT_CONFIG,
    mcp_servers: {
      files: {
        transport: "stdio", command: "uvx", args: [], env: {},
        url: "", auth_token: "", enabled: true,
      },
    },
  } as Record<string, unknown>;
  delete legacy.skills;
  setup({ getConfig: vi.fn().mockResolvedValue(legacy) });
  await screen.findByLabelText("預設專案");
  expect(await screen.findByDisplayValue("uvx")).toBeInTheDocument();
  expect(screen.queryByText("有未儲存的變更")).not.toBeInTheDocument();
});

test("initialTab opens the settings on the requested tab", async () => {
  setup({}, { initialTab: "agent" });
  await screen.findByLabelText("預設專案");
  expect(screen.getByRole("tab", { name: "Agent" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("skill edit button routes through onEditSkill", async () => {
  const onEditSkill = vi.fn();
  setup(
    {
      listSkills: vi.fn().mockResolvedValue([
        {
          name: "honorific-style", description: "敬語",
          enabled: false, confirmed: false, valid: true, errors: [],
        },
      ]),
    },
    { initialTab: "agent", onEditSkill },
  );
  await userEvent.click(await screen.findByRole("button", { name: "編輯" }));
  expect(onEditSkill).toHaveBeenCalledWith("honorific-style");
});

test("dirty draft gates skill editing behind a confirmation", async () => {
  const onEditSkill = vi.fn();
  setup(
    {
      listSkills: vi.fn().mockResolvedValue([
        {
          name: "honorific-style", description: "敬語",
          enabled: false, confirmed: false, valid: true, errors: [],
        },
      ]),
    },
    { initialTab: "agent", onEditSkill },
  );
  // Dirty the draft from another tab, then come back.
  await userEvent.click(await screen.findByRole("tab", { name: "一般" }));
  await userEvent.type(screen.getByLabelText("預設專案"), "-x");
  await userEvent.click(screen.getByRole("tab", { name: "Agent" }));

  await userEvent.click(await screen.findByRole("button", { name: "編輯" }));
  expect(onEditSkill).not.toHaveBeenCalled();
  expect(
    screen.getByRole("dialog", { name: "放棄未儲存的變更？" }),
  ).toBeInTheDocument();
  // Staying keeps the draft and stays put.
  await userEvent.click(screen.getByRole("button", { name: "留下" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(onEditSkill).not.toHaveBeenCalled();
  expect(screen.getByText("有未儲存的變更")).toBeInTheDocument();
  // Discarding proceeds to the editor.
  await userEvent.click(screen.getByRole("button", { name: "編輯" }));
  await userEvent.click(screen.getByRole("button", { name: "放棄修改" }));
  expect(onEditSkill).toHaveBeenCalledWith("honorific-style");
});

test("confirming a skill dirties the draft and saves both flags", async () => {
  const { saveConfig } = setup(
    {
      listSkills: vi.fn().mockResolvedValue([
        {
          name: "honorific-style", description: "敬語",
          enabled: false, confirmed: false, valid: true, errors: [],
        },
      ]),
      getSkill: vi.fn().mockResolvedValue({
        name: "honorific-style",
        content: "---\nname: honorific-style\n---\n\n以敬語翻譯。",
      }),
    },
    { initialTab: "agent" },
  );
  await userEvent.click(await screen.findByLabelText("啟用 honorific-style"));
  expect(await screen.findByText(/以敬語翻譯。/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "確認啟用" }));
  expect(screen.getByText("有未儲存的變更")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(saveConfig).toHaveBeenCalledTimes(1));
  expect(saveConfig.mock.calls[0][0].skills).toEqual({
    "honorific-style": { enabled: true, confirmed: true },
  });
});
