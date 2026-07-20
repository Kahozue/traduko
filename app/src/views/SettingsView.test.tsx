import { screen, waitFor, within } from "@testing-library/react";
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
  dubbing: {
    hf_token: "",
    python: "",
    inference_timesteps: null,
    cfg_value: null,
    seed: null,
    denoise: false,
    diarize_enabled: false,
    dub_enabled: false,
    translate_enabled: false,
  },
  pdf: { python: "" },
  translation_defaults: {
    video: { target_language: "zh-TW", style: "", prompt_override: "" },
    audio: { target_language: "zh-TW", style: "", prompt_override: "" },
    document: { target_language: "zh-TW", style: "", prompt_override: "" },
    comic: { target_language: "zh-TW", style: "", prompt_override: "" },
  },
  audio: { diarize_enabled: false, dub_enabled: false, translate_enabled: true },
    document: { translate_enabled: true, dub_enabled: false },
  asr: {
    engine: "faster_whisper",
    audio_engine: "",
    model: "small",
    macos_locale: "",
    cloud_base_url: "https://api.openai.com/v1",
    cloud_api_key: "",
    cloud_api_key_env: "",
    custom_base_url: "",
    custom_api_key: "",
    custom_api_key_env: "",
    custom_model: "",
    zh_prompt: true,
  },
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
    listGlossaries: vi.fn().mockResolvedValue([]),
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
    "音頻",
    "文件",
    "Agent",
    "整合",
    "關於",
  ]);
  expect(screen.getByRole("tab", { name: "一般" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  for (const el of screen.getAllByText("語音辨識")) {
    expect(el).not.toBeVisible();
  }
});

test("the audio tab shows both the ASR and dubbing engine sections", async () => {
  setup();
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "音頻" }));
  const audioPanel = document.getElementById("settings-panel-audio")!;
  expect(within(audioPanel).getByText("語音辨識")).toBeInTheDocument();
  expect(within(audioPanel).getByText("配音引擎")).toBeInTheDocument();
});

test("tab switches report through onTabChange", async () => {
  const onTabChange = vi.fn();
  setup({}, { onTabChange });
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "音頻" }));
  expect(onTabChange).toHaveBeenCalledWith("audio");
});

test("switching to the video tab reveals the ASR section", async () => {
  setup();
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "影片" }));
  const asrTitles = screen.getAllByText("語音辨識");
  expect(asrTitles.some((el) => el.checkVisibility?.() ?? true)).toBe(true);
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

test("the audio tab shows pipeline default toggles and saves them", async () => {
  const { saveConfig } = setup();
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "音頻" }));
  const audioPanel = document.getElementById("settings-panel-audio")!;
  expect(within(audioPanel).getByText("管線預設")).toBeInTheDocument();
  const dub = within(audioPanel).getByRole("checkbox", { name: "配音" });
  expect(dub).not.toBeChecked();
  expect(within(audioPanel).getByRole("checkbox", { name: "翻譯" })).toBeChecked();
  // Speaker separation is opt-in like dubbing; translating is what an audio
  // task is for, so it stays on.
  expect(
    within(audioPanel).getByRole("checkbox", { name: "說話人分離" }),
  ).not.toBeChecked();
  await userEvent.click(dub);
  await userEvent.click(screen.getByText("儲存"));
  await waitFor(() =>
    expect(saveConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        audio: expect.objectContaining({ dub_enabled: true }),
      }),
    ),
  );
});

test("the video tab carries its own pipeline defaults, all off", async () => {
  const { saveConfig } = setup();
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "影片" }));
  const videoPanel = document.getElementById("settings-panel-video")!;

  expect(within(videoPanel).getByText("管線預設")).toBeInTheDocument();
  // Every optional group is opt-in for video: translation off still exports
  // source-language subtitles, so nothing is lost by defaulting it off.
  for (const name of ["翻譯", "說話人分離", "配音"]) {
    expect(
      within(videoPanel).getByRole("checkbox", { name }),
    ).not.toBeChecked();
  }

  await userEvent.click(within(videoPanel).getByRole("checkbox", { name: "配音" }));
  await userEvent.click(screen.getByText("儲存"));
  await waitFor(() =>
    expect(saveConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        dubbing: expect.objectContaining({ dub_enabled: true }),
      }),
    ),
  );
});

test("the document tab carries translate and dub defaults, and no diarize", async () => {
  setup();
  await screen.findByLabelText("預設專案");
  await userEvent.click(screen.getByRole("tab", { name: "文件" }));
  const documentPanel = document.getElementById("settings-panel-document")!;

  expect(
    within(documentPanel).getByRole("checkbox", { name: "翻譯" }),
  ).toBeChecked();
  expect(
    within(documentPanel).getByRole("checkbox", { name: "配音" }),
  ).not.toBeChecked();
  // A document has no recording, so there are no speakers to separate.
  expect(
    within(documentPanel).queryByRole("checkbox", {
      name: "說話人分離",
      hidden: true,
    }),
  ).toBeNull();
});

test("each domain tab carries its own translation defaults block", async () => {
  const { saveConfig } = setup();
  await screen.findByLabelText("預設專案");

  await userEvent.click(screen.getByRole("tab", { name: "影片" }));
  const videoPanel = document.getElementById("settings-panel-video")!;
  expect(
    within(videoPanel).getByRole("heading", { name: "翻譯" }),
  ).toBeInTheDocument();
  const videoLanguage = within(videoPanel).getByLabelText("目標語言");
  expect(videoLanguage).toHaveValue("zh-TW");
  await userEvent.clear(videoLanguage);
  await userEvent.type(videoLanguage, "ja");
  await userEvent.type(within(videoPanel).getByLabelText("風格"), "簡潔");

  // Sibling domains keep their own values.
  await userEvent.click(screen.getByRole("tab", { name: "音頻" }));
  const audioPanel = document.getElementById("settings-panel-audio")!;
  expect(within(audioPanel).getByLabelText("目標語言")).toHaveValue("zh-TW");
  await userEvent.click(screen.getByRole("tab", { name: "文件" }));
  const documentPanel = document.getElementById("settings-panel-document")!;
  expect(within(documentPanel).getByLabelText("目標語言")).toHaveValue("zh-TW");
  await userEvent.type(
    within(documentPanel).getByLabelText("Prompt 覆寫"),
    "custom",
  );

  await userEvent.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(saveConfig).toHaveBeenCalledTimes(1));
  expect(saveConfig.mock.calls[0][0].translation_defaults).toEqual({
    video: { target_language: "ja", style: "簡潔", prompt_override: "" },
    audio: { target_language: "zh-TW", style: "", prompt_override: "" },
    document: {
      target_language: "zh-TW",
      style: "",
      prompt_override: "custom",
    },
    comic: { target_language: "zh-TW", style: "", prompt_override: "" },
  });
});
