import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ApiError, type ApiClient } from "../../lib/api/client";
import type {
  McpServerConfigDoc,
  McpServerStatus,
  SkillConfigDoc,
  SkillInfo,
} from "../../lib/api/types";
import { renderWithConnection } from "../../test/helpers";
import { AgentSection } from "./AgentSection";

const STDIO_SERVER: McpServerConfigDoc = {
  transport: "stdio",
  command: "uvx",
  args: ["mcp-server-files"],
  env: {},
  url: "",
  auth_token: "",
  enabled: true,
  confirmed: true,
};

const CONNECTED: McpServerStatus = {
  name: "files",
  transport: "stdio",
  enabled: true,
  confirmed: true,
  state: "connected",
  error: "",
  tools: [
    { name: "read", description: "Read a file" },
    { name: "write", description: "Write a file" },
  ],
};

const SKILL: SkillInfo = {
  name: "honorific-style",
  description: "譯文一律使用敬語稱謂",
  enabled: false,
  confirmed: false,
  valid: true,
  errors: [],
};

const SKILL_MD = "---\nname: honorific-style\ndescription: 稱謂規則\n---\n\n以敬語翻譯。";

function setup({
  servers = {},
  status = [],
  skills = {},
  skillList = [],
  api: apiOverrides = {},
}: {
  servers?: Record<string, McpServerConfigDoc>;
  status?: McpServerStatus[];
  skills?: Record<string, SkillConfigDoc>;
  skillList?: SkillInfo[];
  api?: Partial<ApiClient>;
} = {}) {
  const onChange = vi.fn();
  const onSkillsChange = vi.fn();
  const onEditSkill = vi.fn();
  const api: Partial<ApiClient> = {
    listSkills: vi.fn().mockResolvedValue(skillList),
    getSkill: vi.fn().mockResolvedValue({ name: SKILL.name, content: SKILL_MD }),
    createSkill: vi.fn().mockResolvedValue({ created: "x" }),
    deleteSkill: vi.fn().mockResolvedValue({ deleted: true }),
    ...apiOverrides,
  };
  renderWithConnection(
    <AgentSection
      servers={servers}
      status={status}
      skills={skills}
      onChange={onChange}
      onSkillsChange={onSkillsChange}
      onEditSkill={onEditSkill}
    />,
    { api },
  );
  return { onChange, onSkillsChange, onEditSkill, api };
}

function lastCall<T>(fn: ReturnType<typeof vi.fn>): T {
  return fn.mock.calls[fn.mock.calls.length - 1][0] as T;
}

test("renders servers with connection state and tool count", () => {
  setup({ servers: { files: STDIO_SERVER }, status: [CONNECTED] });
  expect(screen.getByDisplayValue("files")).toBeInTheDocument();
  expect(screen.getByText("已連線 · 2 個工具")).toBeInTheDocument();
  expect(screen.getByDisplayValue("uvx")).toBeInTheDocument();
});

test("shows error state with the error message", () => {
  setup({
    servers: { files: STDIO_SERVER },
    status: [{ ...CONNECTED, state: "error", error: "spawn failed", tools: [] }],
  });
  expect(screen.getByText("連線失敗")).toBeInTheDocument();
  expect(screen.getByText("spawn failed")).toBeInTheDocument();
});

test("adding a stdio server emits it disabled and unconfirmed", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "新增伺服器" }));
  // Incomplete row blocks saving.
  expect(onChange).toHaveBeenLastCalledWith(null);
  await userEvent.type(screen.getByLabelText("名稱"), "files");
  await userEvent.type(screen.getByLabelText("指令"), "uvx");
  await userEvent.type(screen.getByLabelText("參數（空白分隔）"), "mcp-server-files --safe");
  const last = lastCall<Record<string, McpServerConfigDoc>>(onChange);
  expect(last.files.command).toBe("uvx");
  expect(last.files.args).toEqual(["mcp-server-files", "--safe"]);
  // New servers stay off until the user flips the toggle and passes the
  // confirmation card; confirmed is sent explicitly so the core's legacy
  // migration cannot treat the entry as pre-confirmed.
  expect(last.files.enabled).toBe(false);
  expect(last.files.confirmed).toBe(false);
});

test("http server without url blocks saving until filled", async () => {
  const { onChange } = setup({ servers: { files: STDIO_SERVER } });
  await userEvent.selectOptions(screen.getByLabelText("傳輸方式"), "http");
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getByText("http 伺服器需要 URL")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("URL"), "http://127.0.0.1:9000/mcp");
  const last = lastCall<Record<string, McpServerConfigDoc>>(onChange);
  expect(last.files.transport).toBe("http");
  expect(last.files.url).toBe("http://127.0.0.1:9000/mcp");
});

test("confirmed server toggles without a dialog", async () => {
  const { onChange } = setup({
    servers: { files: { ...STDIO_SERVER, enabled: false } },
  });
  await userEvent.click(screen.getByLabelText("啟用"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const last = lastCall<Record<string, McpServerConfigDoc>>(onChange);
  expect(last.files.enabled).toBe(true);
});

test("disabling never asks for confirmation", async () => {
  const { onChange } = setup({
    servers: { files: { ...STDIO_SERVER, confirmed: false } },
  });
  await userEvent.click(screen.getByLabelText("啟用"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const last = lastCall<Record<string, McpServerConfigDoc>>(onChange);
  expect(last.files.enabled).toBe(false);
});

test("enabling an unconfirmed server shows its tools; cancel keeps it off", async () => {
  const { onChange } = setup({
    servers: { files: { ...STDIO_SERVER, enabled: false, confirmed: false } },
    status: [{ ...CONNECTED, enabled: false, confirmed: false }],
  });
  await userEvent.click(screen.getByLabelText("啟用"));
  const dialog = screen.getByRole("dialog", { name: "確認掛載 MCP 伺服器" });
  expect(dialog).toBeInTheDocument();
  expect(screen.getByText("read")).toBeInTheDocument();
  expect(screen.getByText("Read a file")).toBeInTheDocument();
  expect(screen.getByText("write")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("啟用")).not.toBeChecked();
  // The draft was never touched.
  expect(onChange).not.toHaveBeenCalled();
});

test("confirming an unconfirmed server writes enabled and confirmed to the draft", async () => {
  const { onChange } = setup({
    servers: { files: { ...STDIO_SERVER, enabled: false, confirmed: false } },
    status: [{ ...CONNECTED, enabled: false, confirmed: false }],
  });
  await userEvent.click(screen.getByLabelText("啟用"));
  await userEvent.click(screen.getByRole("button", { name: "確認啟用" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const last = lastCall<Record<string, McpServerConfigDoc>>(onChange);
  expect(last.files.enabled).toBe(true);
  expect(last.files.confirmed).toBe(true);
  expect(screen.getByLabelText("啟用")).toBeChecked();
});

test("server without a tool list states what confirming means", async () => {
  setup({
    servers: { files: { ...STDIO_SERVER, enabled: false, confirmed: false } },
  });
  await userEvent.click(screen.getByLabelText("啟用"));
  expect(screen.getByText(/尚未回報工具清單/)).toBeInTheDocument();
});

test("remove deletes the server", async () => {
  const { onChange } = setup({ servers: { files: STDIO_SERVER } });
  await userEvent.click(screen.getByRole("button", { name: "移除" }));
  expect(onChange).toHaveBeenLastCalledWith({});
});

test("skill rows show name, description and an error pill when invalid", async () => {
  setup({
    skillList: [
      SKILL,
      {
        name: "broken-skill",
        description: "",
        enabled: false,
        confirmed: false,
        valid: false,
        errors: ["frontmatter is missing a description", "body is empty"],
      },
    ],
  });
  expect(await screen.findByText("honorific-style")).toBeInTheDocument();
  expect(screen.getByText("譯文一律使用敬語稱謂")).toBeInTheDocument();
  expect(screen.getByText("無效")).toBeInTheDocument();
  expect(
    screen.getByText(/frontmatter is missing a description; body is empty/),
  ).toBeInTheDocument();
  // An invalid skill cannot be enabled.
  expect(screen.getByLabelText("啟用 broken-skill")).toBeDisabled();
});

test("empty skill list shows the empty state", async () => {
  setup();
  expect(await screen.findByText("尚無任何 skill，按右上角「建立」新增第一個")).toBeInTheDocument();
});

test("enabling an unconfirmed skill shows the SKILL.md; cancel keeps it off", async () => {
  const { onSkillsChange } = setup({ skillList: [SKILL] });
  await userEvent.click(await screen.findByLabelText("啟用 honorific-style"));
  expect(
    screen.getByRole("dialog", { name: "確認啟用 skill" }),
  ).toBeInTheDocument();
  expect(await screen.findByText(/以敬語翻譯。/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("啟用 honorific-style")).not.toBeChecked();
  expect(onSkillsChange).not.toHaveBeenCalled();
});

test("confirming a skill writes enabled and confirmed into the draft", async () => {
  const { onSkillsChange } = setup({ skillList: [SKILL] });
  await userEvent.click(await screen.findByLabelText("啟用 honorific-style"));
  // The accept button only arms once the content is on screen.
  await screen.findByText(/以敬語翻譯。/);
  await userEvent.click(screen.getByRole("button", { name: "確認啟用" }));
  expect(onSkillsChange).toHaveBeenCalledWith({
    "honorific-style": { enabled: true, confirmed: true },
  });
});

test("skill confirm stays disabled until the content is visible", async () => {
  let resolve: (value: { name: string; content: string }) => void = () => {};
  const getSkill = vi.fn().mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  setup({ skillList: [SKILL], api: { getSkill } });
  await userEvent.click(await screen.findByLabelText("啟用 honorific-style"));
  expect(screen.getByRole("button", { name: "確認啟用" })).toBeDisabled();
  resolve({ name: SKILL.name, content: SKILL_MD });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "確認啟用" })).toBeEnabled(),
  );
});

test("skill confirm stays disabled when the content fails to load", async () => {
  setup({
    skillList: [SKILL],
    api: { getSkill: vi.fn().mockRejectedValue(new ApiError(500, "boom")) },
  });
  await userEvent.click(await screen.findByLabelText("啟用 honorific-style"));
  expect(await screen.findByText("無法載入 skill 內容")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "確認啟用" })).toBeDisabled();
});

test("enabled but unconfirmed skill offers reconfirmation", async () => {
  const { onSkillsChange } = setup({
    skillList: [{ ...SKILL, enabled: true, confirmed: false }],
    skills: { "honorific-style": { enabled: true, confirmed: false } },
  });
  expect(await screen.findByText("未確認")).toBeInTheDocument();
  expect(
    screen.getByText("內容已變更，重新確認後才會提供給校對 agent"),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重新確認" }));
  expect(
    screen.getByRole("dialog", { name: "確認啟用 skill" }),
  ).toBeInTheDocument();
  await screen.findByText(/以敬語翻譯。/);
  await userEvent.click(screen.getByRole("button", { name: "確認啟用" }));
  expect(onSkillsChange).toHaveBeenCalledWith({
    "honorific-style": { enabled: true, confirmed: true },
  });
});

test("already-confirmed skill toggles directly", async () => {
  const { onSkillsChange } = setup({
    skillList: [{ ...SKILL, confirmed: true }],
    skills: { "honorific-style": { enabled: false, confirmed: true } },
  });
  await userEvent.click(await screen.findByLabelText("啟用 honorific-style"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(onSkillsChange).toHaveBeenCalledWith({
    "honorific-style": { enabled: true, confirmed: true },
  });
});

test("disabling a skill keeps its confirmed flag", async () => {
  const { onSkillsChange } = setup({
    skillList: [{ ...SKILL, enabled: true, confirmed: true }],
    skills: { "honorific-style": { enabled: true, confirmed: true } },
  });
  await userEvent.click(await screen.findByLabelText("啟用 honorific-style"));
  expect(onSkillsChange).toHaveBeenCalledWith({
    "honorific-style": { enabled: false, confirmed: true },
  });
});

test("add form validates the name before calling the api", async () => {
  const { api } = setup();
  // The create form is transient: it opens from the section-header button.
  await userEvent.click(await screen.findByRole("button", { name: "建立" }));
  const input = await screen.findByLabelText("新 skill 名稱");
  await userEvent.type(input, "Bad_Name");
  expect(
    screen.getByText("名稱須為小寫英數字，可用連字號分隔，最長 64 字元"),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "確認建立" })).toBeDisabled();
  expect(api.createSkill).not.toHaveBeenCalled();
  await userEvent.clear(input);
  await userEvent.type(input, "my-style");
  await userEvent.click(screen.getByRole("button", { name: "確認建立" }));
  await waitFor(() => expect(api.createSkill).toHaveBeenCalledWith("my-style"));
});

test("duplicate skill name surfaces the conflict", async () => {
  const { api } = setup({
    api: {
      createSkill: vi
        .fn()
        .mockRejectedValue(new ApiError(409, "skill already exists: my-style")),
    },
  });
  await userEvent.click(await screen.findByRole("button", { name: "建立" }));
  await userEvent.type(await screen.findByLabelText("新 skill 名稱"), "my-style");
  await userEvent.click(screen.getByRole("button", { name: "確認建立" }));
  expect(await screen.findByText("同名 skill 已存在")).toBeInTheDocument();
  expect(api.createSkill).toHaveBeenCalledTimes(1);
});

test("deleting a skill calls the api and drops the draft entry", async () => {
  const { api, onSkillsChange } = setup({
    skillList: [{ ...SKILL, enabled: true, confirmed: true }],
    skills: { "honorific-style": { enabled: true, confirmed: true } },
  });
  await screen.findByText("honorific-style");
  await userEvent.click(screen.getByRole("button", { name: "移除" }));
  await waitFor(() => expect(api.deleteSkill).toHaveBeenCalledWith("honorific-style"));
  await waitFor(() => expect(onSkillsChange).toHaveBeenCalledWith({}));
});

test("edit button hands the skill to the editor callback", async () => {
  const { onEditSkill } = setup({ skillList: [SKILL] });
  await screen.findByText("honorific-style");
  await userEvent.click(screen.getByRole("button", { name: "編輯" }));
  expect(onEditSkill).toHaveBeenCalledWith("honorific-style");
});

test("config-only missing skill is listed until removed from the draft", async () => {
  setup({
    skillList: [
      {
        name: "gone-skill",
        description: "",
        enabled: true,
        confirmed: true,
        valid: false,
        errors: ["missing"],
      },
    ],
    skills: { "gone-skill": { enabled: true, confirmed: true } },
  });
  expect(await screen.findByText("gone-skill")).toBeInTheDocument();
  expect(screen.getByText(/missing/)).toBeInTheDocument();
  // No file on disk, so there is nothing to open in the editor.
  expect(screen.queryByRole("button", { name: "編輯" })).not.toBeInTheDocument();
});

test("missing skill already dropped from the draft is hidden", async () => {
  setup({
    skillList: [
      {
        name: "gone-skill",
        description: "",
        enabled: false,
        confirmed: false,
        valid: false,
        errors: ["missing"],
      },
    ],
    skills: {},
  });
  await screen.findByText("尚無任何 skill，按右上角「建立」新增第一個");
  expect(screen.queryByText("gone-skill")).not.toBeInTheDocument();
});

test("built-in candidates can be added and go through the normal gates", async () => {
  const onChange = vi.fn();
  const api: Partial<ApiClient> = {
    listSkills: vi.fn().mockResolvedValue([]),
    getMcpCandidates: vi.fn().mockResolvedValue([
      {
        name: "memory",
        available: true,
        install_hint: "",
        heavy: false,
        config: {
          transport: "stdio",
          command: "npx",
          args: ["-y", "@modelcontextprotocol/server-memory"],
          env: { MEMORY_FILE_PATH: "/data/mcp-memory.json" },
          url: "",
          auth_token: "",
          enabled: false,
          confirmed: false,
        },
      },
      {
        name: "fetch",
        available: false,
        install_hint: "pip install uv（提供 uvx）",
        heavy: false,
        config: {
          transport: "stdio",
          command: "uvx",
          args: ["mcp-server-fetch"],
          env: {},
          url: "",
          auth_token: "",
          enabled: false,
          confirmed: false,
        },
      },
    ]),
  };
  renderWithConnection(
    <AgentSection
      servers={{}}
      status={[]}
      skills={{}}
      onChange={onChange}
      onSkillsChange={() => {}}
    />,
    { api },
  );
  await screen.findByText(/預設候選/);
  const addButtons = screen.getAllByRole("button", { name: "加入" });
  expect(addButtons).toHaveLength(2);
  // Unavailable command: add disabled, install hint shown.
  expect(screen.getByText(/pip install uv/)).toBeInTheDocument();
  const disabledAdd = addButtons.find((el) => (el as HTMLButtonElement).disabled);
  expect(disabledAdd).toBeTruthy();
  const enabledAdd = addButtons.find((el) => !(el as HTMLButtonElement).disabled)!;
  await userEvent.click(enabledAdd);
  await waitFor(() =>
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        memory: expect.objectContaining({ enabled: false, confirmed: false }),
      }),
    ),
  );
});
