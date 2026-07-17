import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ApiError, type ApiClient } from "../lib/api/client";
import type { AssistantMessageDoc, AssistantReply } from "../lib/api/types";
import { renderWithConnection } from "../test/helpers";
import { AssistantPanel } from "./AssistantPanel";

const HISTORY: AssistantMessageDoc[] = [
  { role: "user", text: "任務 abc 進度如何？", ts: "2026-07-18T01:00:00+00:00" },
  {
    role: "assistant",
    text: "任務 abc 目前執行中，已完成翻譯階段。",
    ts: "2026-07-18T01:00:01+00:00",
  },
];

function setup({
  history = [],
  api: apiOverrides = {},
}: {
  history?: AssistantMessageDoc[];
  api?: Partial<ApiClient>;
} = {}) {
  const onClose = vi.fn();
  const api: Partial<ApiClient> = {
    getAssistantHistory: vi.fn().mockResolvedValue(history),
    sendAssistantMessage: vi.fn(),
    clearAssistant: vi.fn().mockResolvedValue({ cleared: true }),
    ...apiOverrides,
  };
  renderWithConnection(<AssistantPanel onClose={onClose} />, { api });
  return { onClose, api };
}

test("loads history and renders user and assistant bubbles", async () => {
  setup({ history: HISTORY });
  expect(await screen.findByText("任務 abc 進度如何？")).toBeInTheDocument();
  expect(screen.getByText("任務 abc 目前執行中，已完成翻譯階段。")).toBeInTheDocument();
});

test("empty history shows the empty state", async () => {
  setup();
  expect(await screen.findByText("尚無對話，輸入訊息開始")).toBeInTheDocument();
});

test("sending a message renders the reply and clears the draft", async () => {
  const reply: AssistantReply = {
    reply: "已為你查詢，任務 xyz 尚在排隊。",
    proposal_ids: [],
    converged: true,
    reason: "",
    history: [
      { role: "user", text: "任務 xyz 呢？", ts: "2026-07-18T01:05:00+00:00" },
      {
        role: "assistant",
        text: "已為你查詢，任務 xyz 尚在排隊。",
        ts: "2026-07-18T01:05:01+00:00",
        proposal_ids: [],
      },
    ],
  };
  const sendAssistantMessage = vi.fn().mockResolvedValue(reply);
  const { api } = setup({ api: { sendAssistantMessage } });
  await screen.findByText("尚無對話，輸入訊息開始");
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  await userEvent.type(textarea, "任務 xyz 呢？");
  await userEvent.click(screen.getByRole("button", { name: "傳送" }));
  expect(api.sendAssistantMessage).toHaveBeenCalledWith("任務 xyz 呢？");
  expect(await screen.findByText("已為你查詢，任務 xyz 尚在排隊。")).toBeInTheDocument();
  expect(textarea).toHaveValue("");
});

test("Enter sends the message; Shift+Enter inserts a newline instead", async () => {
  const reply: AssistantReply = {
    reply: "收到",
    proposal_ids: [],
    converged: true,
    reason: "",
    history: [
      { role: "user", text: "第一行\n第二行", ts: "2026-07-18T01:06:00+00:00" },
      { role: "assistant", text: "收到", ts: "2026-07-18T01:06:01+00:00", proposal_ids: [] },
    ],
  };
  const sendAssistantMessage = vi.fn().mockResolvedValue(reply);
  setup({ api: { sendAssistantMessage } });
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  await userEvent.type(textarea, "第一行");
  await userEvent.type(textarea, "{Shift>}{Enter}{/Shift}");
  expect(sendAssistantMessage).not.toHaveBeenCalled();
  expect(textarea).toHaveValue("第一行\n");
  await userEvent.type(textarea, "第二行");
  await userEvent.type(textarea, "{Enter}");
  expect(sendAssistantMessage).toHaveBeenCalledWith("第一行\n第二行");
});

test("busy state disables input and shows the processing indicator", async () => {
  let resolve: (value: AssistantReply) => void = () => {};
  const sendAssistantMessage = vi.fn().mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  setup({ api: { sendAssistantMessage } });
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  await userEvent.type(textarea, "hello");
  await userEvent.click(screen.getByRole("button", { name: "傳送" }));
  expect(screen.getByText("助理處理中")).toBeInTheDocument();
  expect(textarea).toBeDisabled();
  expect(screen.getByRole("button", { name: "傳送" })).toBeDisabled();
  resolve({
    reply: "ok",
    proposal_ids: [],
    converged: true,
    reason: "",
    history: [{ role: "assistant", text: "ok", ts: "2026-07-18T01:07:00+00:00" }],
  });
  await waitFor(() => expect(screen.queryByText("助理處理中")).not.toBeInTheDocument());
  expect(textarea).toBeEnabled();
});

test("clear calls the api and empties the message flow", async () => {
  const { api } = setup({ history: HISTORY });
  await screen.findByText("任務 abc 進度如何？");
  await userEvent.click(screen.getByRole("button", { name: "清空" }));
  await waitFor(() => expect(api.clearAssistant).toHaveBeenCalled());
  expect(await screen.findByText("尚無對話，輸入訊息開始")).toBeInTheDocument();
  expect(screen.queryByText("任務 abc 進度如何？")).not.toBeInTheDocument();
});

test("close button calls onClose", async () => {
  const { onClose } = setup();
  await userEvent.click(screen.getByRole("button", { name: "關閉" }));
  expect(onClose).toHaveBeenCalled();
});

test("409 (no provider) shows the settings guidance text, not the raw error", async () => {
  const sendAssistantMessage = vi
    .fn()
    .mockRejectedValue(new ApiError(409, "no usable llm provider configured"));
  setup({ api: { sendAssistantMessage } });
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  await userEvent.type(textarea, "hello");
  await userEvent.click(screen.getByRole("button", { name: "傳送" }));
  expect(
    await screen.findByText("尚未設定可用的 LLM 供應商，請至設定新增供應商後再試一次。"),
  ).toBeInTheDocument();
  expect(screen.queryByText("no usable llm provider configured")).not.toBeInTheDocument();
});

test("a generic send failure shows a generic error message", async () => {
  const sendAssistantMessage = vi.fn().mockRejectedValue(new ApiError(500, "boom"));
  setup({ api: { sendAssistantMessage } });
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  await userEvent.type(textarea, "hello");
  await userEvent.click(screen.getByRole("button", { name: "傳送" }));
  expect(await screen.findByText("傳送失敗，請稍後再試。")).toBeInTheDocument();
});
