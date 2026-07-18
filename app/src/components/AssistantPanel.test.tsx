import { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ApiError, type ApiClient } from "../lib/api/client";
import type { AssistantMessageDoc, AssistantReply, ProposalDoc } from "../lib/api/types";
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

const PROPOSAL: ProposalDoc = {
  id: "prop-1",
  kind: "config",
  reason: "調高單任務預算上限以配合本月大量任務。",
  patch: { default_project: "anime" },
  diff: [
    "--- traduko.yaml (current)",
    "+++ traduko.yaml (proposed)",
    "@@ -1,3 +1,3 @@",
    " budget:",
    "-default_project: default",
    "+default_project: anime",
    "",
  ].join("\n"),
  status: "pending",
  created_at: "2026-07-18T01:00:02+00:00",
};

const HISTORY_WITH_PROPOSAL: AssistantMessageDoc[] = [
  { role: "user", text: "把預設專案改成 anime", ts: "2026-07-18T01:00:00+00:00" },
  {
    role: "assistant",
    text: "已建立提案，請確認後核准。",
    ts: "2026-07-18T01:00:02+00:00",
    proposal_ids: ["prop-1"],
  },
];

function setup({
  history = [],
  api: apiOverrides = {},
  queryClient,
}: {
  history?: AssistantMessageDoc[];
  api?: Partial<ApiClient>;
  queryClient?: QueryClient;
} = {}) {
  const onClose = vi.fn();
  const api: Partial<ApiClient> = {
    getAssistantHistory: vi.fn().mockResolvedValue(history),
    sendAssistantMessage: vi.fn(),
    clearAssistant: vi.fn().mockResolvedValue({ cleared: true }),
    listProposals: vi.fn().mockResolvedValue([]),
    listAssistantSessions: vi.fn().mockResolvedValue([]),
    activateAssistantSession: vi.fn().mockResolvedValue({ active: "s1" }),
    archiveAssistantSession: vi.fn().mockResolvedValue({ archived: true }),
    deleteAssistantSession: vi.fn().mockResolvedValue({ deleted: true }),
    ...apiOverrides,
  };
  renderWithConnection(<AssistantPanel onClose={onClose} />, { api, queryClient });
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

test("new chat calls clear and empties the message flow", async () => {
  const { api } = setup({ history: HISTORY });
  await screen.findByText("任務 abc 進度如何？");
  await userEvent.click(screen.getByRole("button", { name: "新對話" }));
  await waitFor(() => expect(api.clearAssistant).toHaveBeenCalled());
  expect(await screen.findByText("尚無對話，輸入訊息開始")).toBeInTheDocument();
  expect(screen.queryByText("任務 abc 進度如何？")).not.toBeInTheDocument();
});

test("close button calls onClose", async () => {
  const { onClose } = setup();
  await userEvent.click(screen.getByRole("button", { name: "關閉" }));
  expect(onClose).toHaveBeenCalled();
});

test("an assistant reply is rendered as markdown and shows its model chip", async () => {
  setup({
    history: [
      {
        role: "assistant",
        text: "已完成 **翻譯** 階段。",
        ts: "2026-07-18T01:00:01+00:00",
        model: "gpt-4o-mini",
      },
    ],
  });
  expect((await screen.findByText("翻譯")).tagName).toBe("STRONG");
  expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
});

test("editing a user message prefills the draft and resends with edit_index", async () => {
  const reply: AssistantReply = {
    reply: "已重新處理。",
    proposal_ids: [],
    converged: true,
    reason: "",
    history: [
      { role: "user", text: "改後的問題", ts: "2026-07-18T02:00:00+00:00" },
      { role: "assistant", text: "已重新處理。", ts: "2026-07-18T02:00:01+00:00" },
    ],
  };
  const sendAssistantMessage = vi.fn().mockResolvedValue(reply);
  setup({ history: HISTORY, api: { sendAssistantMessage } });
  await screen.findByText("任務 abc 進度如何？");
  await userEvent.click(screen.getByRole("button", { name: "編輯" }));
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  expect(textarea).toHaveValue("任務 abc 進度如何？");
  await userEvent.clear(textarea);
  await userEvent.type(textarea, "改後的問題");
  await userEvent.click(screen.getByRole("button", { name: "傳送" }));
  expect(sendAssistantMessage).toHaveBeenCalledWith("改後的問題", {
    editIndex: 0,
    images: undefined,
  });
});

test("history drawer lists sessions and bulk-deletes the selected ones", async () => {
  const listAssistantSessions = vi.fn().mockResolvedValue([
    {
      id: "s1",
      title: "第一段對話",
      archived: false,
      created_at: "2026-07-18T01:00:00+00:00",
      updated_at: "2026-07-18T01:00:00+00:00",
      message_count: 4,
      active: true,
    },
  ]);
  const deleteAssistantSession = vi.fn().mockResolvedValue({ deleted: true });
  setup({ api: { listAssistantSessions, deleteAssistantSession } });
  await userEvent.click(screen.getByRole("button", { name: "歷史紀錄" }));
  expect(await screen.findByText("第一段對話")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", { name: /第一段對話/ }));
  await userEvent.click(screen.getByRole("button", { name: "刪除" }));
  await waitFor(() => expect(deleteAssistantSession).toHaveBeenCalledWith("s1"));
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

test("a pending proposal renders reason, diff lines, status pill and both action buttons", async () => {
  setup({
    history: HISTORY_WITH_PROPOSAL,
    api: { listProposals: vi.fn().mockResolvedValue([PROPOSAL]) },
  });
  expect(await screen.findByText("調高單任務預算上限以配合本月大量任務。")).toBeInTheDocument();
  expect(screen.getByText("待處理")).toBeInTheDocument();
  expect(screen.getByText("-default_project: default")).toBeInTheDocument();
  expect(screen.getByText("+default_project: anime")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "核准" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "駁回" })).toBeInTheDocument();
});

test("an applied proposal shows its pill but no action buttons", async () => {
  setup({
    history: HISTORY_WITH_PROPOSAL,
    api: { listProposals: vi.fn().mockResolvedValue([{ ...PROPOSAL, status: "applied" }]) },
  });
  expect(await screen.findByText("已套用")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "核准" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "駁回" })).not.toBeInTheDocument();
});

test("a proposal id with no matching proposal (after load) renders a removed note", async () => {
  setup({
    history: [
      {
        role: "assistant",
        text: "已建立提案。",
        ts: "2026-07-18T01:00:02+00:00",
        proposal_ids: ["gone"],
      },
    ],
    api: { listProposals: vi.fn().mockResolvedValue([]) },
  });
  expect(await screen.findByText("此提案已無法取得。")).toBeInTheDocument();
});

test("a proposal created by the just-sent message renders its card without remount", async () => {
  const reply: AssistantReply = {
    reply: "已建立提案，請確認後核准。",
    proposal_ids: ["prop-1"],
    converged: true,
    reason: "",
    history: HISTORY_WITH_PROPOSAL,
  };
  // First fetch (at mount) predates the proposal; the refetch triggered by
  // send.onSuccess's invalidation returns it.
  const listProposals = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([PROPOSAL]);
  const sendAssistantMessage = vi.fn().mockResolvedValue(reply);
  setup({ api: { listProposals, sendAssistantMessage } });
  await screen.findByText("尚無對話，輸入訊息開始");
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  await userEvent.type(textarea, "把預設專案改成 anime");
  await userEvent.click(screen.getByRole("button", { name: "傳送" }));
  expect(await screen.findByText("調高單任務預算上限以配合本月大量任務。")).toBeInTheDocument();
  expect(screen.getByText("待處理")).toBeInTheDocument();
  expect(screen.getByText("+default_project: anime")).toBeInTheDocument();
  expect(listProposals).toHaveBeenCalledTimes(2);
  expect(screen.queryByText("此提案已無法取得。")).not.toBeInTheDocument();
});

test("a proposals fetch failure does not render the removed note", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  setup({
    history: HISTORY_WITH_PROPOSAL,
    api: { listProposals: vi.fn().mockRejectedValue(new ApiError(500, "boom")) },
    queryClient,
  });
  expect(await screen.findByText("已建立提案，請確認後核准。")).toBeInTheDocument();
  await waitFor(() =>
    expect(queryClient.getQueryState(["proposals"])?.status).toBe("error"),
  );
  expect(screen.queryByText("此提案已無法取得。")).not.toBeInTheDocument();
});

test("approving a pending proposal calls approveProposal and invalidates proposals and config", async () => {
  const approveProposal = vi.fn().mockResolvedValue({});
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  setup({
    history: HISTORY_WITH_PROPOSAL,
    api: { listProposals: vi.fn().mockResolvedValue([PROPOSAL]), approveProposal },
    queryClient,
  });
  await userEvent.click(await screen.findByRole("button", { name: "核准" }));
  await waitFor(() => expect(approveProposal).toHaveBeenCalledWith("prop-1"));
  await waitFor(() =>
    expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["proposals"] })),
  );
  expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["config"] }));
});

test("rejecting a pending proposal calls rejectProposal and invalidates proposals", async () => {
  const rejectProposal = vi.fn().mockResolvedValue({ ...PROPOSAL, status: "rejected" });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  setup({
    history: HISTORY_WITH_PROPOSAL,
    api: { listProposals: vi.fn().mockResolvedValue([PROPOSAL]), rejectProposal },
    queryClient,
  });
  await userEvent.click(await screen.findByRole("button", { name: "駁回" }));
  await waitFor(() => expect(rejectProposal).toHaveBeenCalledWith("prop-1"));
  await waitFor(() =>
    expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["proposals"] })),
  );
});

test("a failed approve shows an inline error on that proposal's card", async () => {
  const approveProposal = vi.fn().mockRejectedValue(new ApiError(500, "boom"));
  setup({
    history: HISTORY_WITH_PROPOSAL,
    api: { listProposals: vi.fn().mockResolvedValue([PROPOSAL]), approveProposal },
  });
  await userEvent.click(await screen.findByRole("button", { name: "核准" }));
  expect(await screen.findByText("核准失敗，請稍後再試。")).toBeInTheDocument();
});

function pasteImage(textarea: HTMLElement, file: File) {
  fireEvent.paste(textarea, {
    clipboardData: {
      items: [{ kind: "file", type: file.type, getAsFile: () => file }],
    },
  });
}

test("pasting a clipboard image uploads it and adds an attachment chip", async () => {
  const uploadAssistantAttachment = vi
    .fn()
    .mockResolvedValue({ path: "/data/assistant/attachments/20260718.png" });
  setup({ api: { uploadAssistantAttachment } });
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  pasteImage(textarea, new File([new Uint8Array([1, 2, 3])], "clip.png", { type: "image/png" }));
  await waitFor(() =>
    expect(uploadAssistantAttachment).toHaveBeenCalledWith("image/png", expect.any(String)),
  );
  expect(await screen.findByText("20260718.png")).toBeInTheDocument();
});

test("a failed clipboard upload shows the attach error hint", async () => {
  const uploadAssistantAttachment = vi.fn().mockRejectedValue(new ApiError(500, "disk full"));
  setup({ api: { uploadAssistantAttachment } });
  const textarea = screen.getByPlaceholderText("輸入訊息，Enter 送出、Shift+Enter 換行");
  pasteImage(textarea, new File([new Uint8Array([1])], "clip.png", { type: "image/png" }));
  expect(await screen.findByText("剪貼板圖片附加失敗，請再試一次")).toBeInTheDocument();
});
