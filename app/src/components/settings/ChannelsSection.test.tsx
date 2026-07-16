import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ChannelConfigDoc, NotifyTestResult } from "../../lib/api/types";
import { ChannelsSection } from "./ChannelsSection";

function setup(
  channels: ChannelConfigDoc[] = [],
  onTest: (channel: ChannelConfigDoc) => Promise<NotifyTestResult> = () =>
    Promise.resolve({ ok: true }),
) {
  const onChange = vi.fn();
  render(<ChannelsSection channels={channels} onChange={onChange} onTest={onTest} />);
  return { onChange };
}

test("new discord channel requires webhook url then propagates", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "新增管道" }));
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getByText("必填欄位未填")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Webhook 網址"), "https://d/hook");
  expect(onChange).toHaveBeenLastCalledWith([
    { type: "discord", webhook_url: "https://d/hook" },
  ]);
});

test("email to_addrs accepts comma separated list", async () => {
  const { onChange } = setup([
    {
      type: "email",
      smtp_host: "smtp.example.com",
      from_addr: "bot@example.com",
      to_addrs: ["a@example.com"],
    },
  ]);
  const addrs = screen.getByLabelText("收件位址（逗號分隔）");
  await userEvent.type(addrs, ", b@example.com");
  const last = (onChange.mock.lastCall as unknown[])[0] as ChannelConfigDoc[];
  expect(last[0].to_addrs).toEqual(["a@example.com", "b@example.com"]);
});

test("invalid smtp port is rejected", async () => {
  const { onChange } = setup([
    {
      type: "email",
      smtp_host: "smtp.example.com",
      from_addr: "bot@example.com",
      to_addrs: ["a@example.com"],
    },
  ]);
  await userEvent.type(screen.getByLabelText("SMTP 埠"), "abc");
  expect(onChange).toHaveBeenLastCalledWith(null);
});

test("custom events toggle prefills defaults and edits membership", async () => {
  const { onChange } = setup([{ type: "discord", webhook_url: "https://d/hook" }]);
  await userEvent.click(screen.getByLabelText("自訂事件"));
  let last = (onChange.mock.lastCall as unknown[])[0] as ChannelConfigDoc[];
  expect(last[0].events).toContain("task_completed");
  expect(last[0].events).not.toContain("stage_progress");
  await userEvent.click(screen.getByLabelText("任務完成"));
  last = (onChange.mock.lastCall as unknown[])[0] as ChannelConfigDoc[];
  expect(last[0].events).not.toContain("task_completed");
  await userEvent.click(screen.getByLabelText("自訂事件"));
  last = (onChange.mock.lastCall as unknown[])[0] as ChannelConfigDoc[];
  expect(last[0].events).toBeUndefined();
});

test("send test shows success and failure results", async () => {
  const onTest = vi
    .fn<(channel: ChannelConfigDoc) => Promise<NotifyTestResult>>()
    .mockResolvedValueOnce({ ok: true })
    .mockResolvedValueOnce({ ok: false, error: "boom" });
  setup([{ type: "discord", webhook_url: "https://d/hook" }], onTest);
  await userEvent.click(screen.getByRole("button", { name: "傳送測試" }));
  await waitFor(() => expect(screen.getByText("測試傳送成功")).toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: "傳送測試" }));
  await waitFor(() =>
    expect(screen.getByText("測試傳送失敗：boom")).toBeInTheDocument(),
  );
  expect(onTest).toHaveBeenCalledWith({ type: "discord", webhook_url: "https://d/hook" });
});

test("switching type rebuilds fields and keeps custom events", async () => {
  const { onChange } = setup([
    { type: "discord", webhook_url: "https://d/hook", events: ["task_completed"] },
  ]);
  await userEvent.selectOptions(screen.getByLabelText("類型"), "email");
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getByLabelText("SMTP 主機")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("SMTP 主機"), "smtp.example.com");
  await userEvent.type(screen.getByLabelText("寄件位址"), "bot@example.com");
  await userEvent.type(screen.getByLabelText("收件位址（逗號分隔）"), "a@example.com");
  const last = (onChange.mock.lastCall as unknown[])[0] as ChannelConfigDoc[];
  expect(last[0]).toEqual({
    type: "email",
    events: ["task_completed"],
    smtp_host: "smtp.example.com",
    from_addr: "bot@example.com",
    to_addrs: ["a@example.com"],
  });
});

test("removing a channel propagates empty list", async () => {
  const { onChange } = setup([{ type: "discord", webhook_url: "https://d/hook" }]);
  await userEvent.click(screen.getByRole("button", { name: "移除" }));
  expect(onChange).toHaveBeenLastCalledWith([]);
});
