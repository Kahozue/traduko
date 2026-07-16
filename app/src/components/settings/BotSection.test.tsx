import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { DiscordBotConfigDoc } from "../../lib/api/types";
import { BotSection } from "./BotSection";

const BASE: DiscordBotConfigDoc = {
  enabled: false,
  bot_token: "",
  bot_token_env: "",
  guild_id: "",
  channel_id: "",
  allowed_user_ids: [],
};

function setup(bot: DiscordBotConfigDoc = BASE) {
  const onChange = vi.fn();
  render(<BotSection bot={bot} onChange={onChange} />);
  return { onChange };
}

test("enabling the bot propagates the flag", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByLabelText("啟用 Discord bot"));
  expect(onChange).toHaveBeenLastCalledWith({ ...BASE, enabled: true });
});

test("token field is masked with a reveal toggle", async () => {
  setup({ ...BASE, bot_token: "secret" });
  expect(screen.getByLabelText("Bot token")).toHaveAttribute("type", "password");
  await userEvent.click(screen.getByRole("button", { name: "顯示" }));
  expect(screen.getByLabelText("Bot token")).toHaveAttribute("type", "text");
});

test("user id list is comma separated and normalized", async () => {
  const { onChange } = setup();
  const input = screen.getByLabelText("允許的使用者 ID（逗號分隔）");
  await userEvent.type(input, "123, 456");
  expect(onChange).toHaveBeenLastCalledWith({
    ...BASE,
    allowed_user_ids: ["123", "456"],
  });
});

test("non-numeric ids invalidate the section", async () => {
  const { onChange } = setup();
  await userEvent.type(screen.getByLabelText("伺服器 ID（guild）"), "abc");
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getAllByText("ID 須為數字").length).toBeGreaterThan(0);
});

test("unknown keys survive edits", async () => {
  const { onChange } = setup({ ...BASE, future_key: "kept" } as DiscordBotConfigDoc);
  await userEvent.type(screen.getByLabelText("進度訊息頻道 ID"), "9");
  expect(onChange).toHaveBeenLastCalledWith({
    ...BASE,
    future_key: "kept",
    channel_id: "9",
  });
});
