import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { McpServerConfigDoc, McpServerStatus } from "../../lib/api/types";
import { AgentSection } from "./AgentSection";

const STDIO_SERVER: McpServerConfigDoc = {
  transport: "stdio",
  command: "uvx",
  args: ["mcp-server-files"],
  env: {},
  url: "",
  auth_token: "",
  enabled: true,
};

const CONNECTED: McpServerStatus = {
  name: "files",
  transport: "stdio",
  enabled: true,
  state: "connected",
  error: "",
  tools: ["read", "write"],
};

test("renders servers with connection state and tool count", () => {
  render(
    <AgentSection
      servers={{ files: STDIO_SERVER }}
      status={[CONNECTED]}
      onChange={() => {}}
    />,
  );
  expect(screen.getByDisplayValue("files")).toBeInTheDocument();
  expect(screen.getByText("已連線 · 2 個工具")).toBeInTheDocument();
  expect(screen.getByDisplayValue("uvx")).toBeInTheDocument();
});

test("shows error state with the error message", () => {
  render(
    <AgentSection
      servers={{ files: STDIO_SERVER }}
      status={[{ ...CONNECTED, state: "error", error: "spawn failed", tools: [] }]}
      onChange={() => {}}
    />,
  );
  expect(screen.getByText("連線失敗")).toBeInTheDocument();
  expect(screen.getByText("spawn failed")).toBeInTheDocument();
});

test("adding a stdio server emits it once command and name are filled", async () => {
  const onChange = vi.fn();
  render(<AgentSection servers={{}} status={[]} onChange={onChange} />);
  await userEvent.click(screen.getByRole("button", { name: "新增伺服器" }));
  // Incomplete row blocks saving.
  expect(onChange).toHaveBeenLastCalledWith(null);
  await userEvent.type(screen.getByLabelText("名稱"), "files");
  await userEvent.type(screen.getByLabelText("指令"), "uvx");
  await userEvent.type(screen.getByLabelText("參數（空白分隔）"), "mcp-server-files --safe");
  const last = onChange.mock.calls[onChange.mock.calls.length - 1][0] as Record<string, McpServerConfigDoc>;
  expect(last.files.command).toBe("uvx");
  expect(last.files.args).toEqual(["mcp-server-files", "--safe"]);
  expect(last.files.enabled).toBe(true);
});

test("http server without url blocks saving until filled", async () => {
  const onChange = vi.fn();
  render(
    <AgentSection servers={{ files: STDIO_SERVER }} status={[]} onChange={onChange} />,
  );
  await userEvent.selectOptions(screen.getByLabelText("傳輸方式"), "http");
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getByText("http 伺服器需要 URL")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("URL"), "http://127.0.0.1:9000/mcp");
  const last = onChange.mock.calls[onChange.mock.calls.length - 1][0] as Record<string, McpServerConfigDoc>;
  expect(last.files.transport).toBe("http");
  expect(last.files.url).toBe("http://127.0.0.1:9000/mcp");
});

test("enable toggle flips the enabled flag", async () => {
  const onChange = vi.fn();
  render(
    <AgentSection servers={{ files: STDIO_SERVER }} status={[]} onChange={onChange} />,
  );
  await userEvent.click(screen.getByLabelText("啟用"));
  const last = onChange.mock.calls[onChange.mock.calls.length - 1][0] as Record<string, McpServerConfigDoc>;
  expect(last.files.enabled).toBe(false);
});

test("remove deletes the server", async () => {
  const onChange = vi.fn();
  render(
    <AgentSection servers={{ files: STDIO_SERVER }} status={[]} onChange={onChange} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "移除" }));
  expect(onChange).toHaveBeenLastCalledWith({});
});
