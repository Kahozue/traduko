import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ProviderConfigDoc } from "../../lib/api/types";
import { ProvidersSection } from "./ProvidersSection";

function setup(providers: Record<string, ProviderConfigDoc> = {}) {
  const onChange = vi.fn();
  render(<ProvidersSection providers={providers} onChange={onChange} />);
  return { onChange };
}

test("adding a provider with name and base_url propagates a record", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "新增供應商" }));
  expect(onChange).toHaveBeenLastCalledWith(null);
  await userEvent.type(screen.getByLabelText("名稱"), "deepseek");
  await userEvent.type(
    screen.getByLabelText("API 位址（base_url）"),
    "https://api.deepseek.com/v1",
  );
  expect(onChange).toHaveBeenLastCalledWith({
    deepseek: { type: "openai_compat", base_url: "https://api.deepseek.com/v1" },
  });
});

test("duplicate names are invalid", async () => {
  const { onChange } = setup({
    a: { type: "openai_compat", base_url: "https://x/v1" },
    b: { type: "openai_compat", base_url: "https://y/v1" },
  });
  const names = screen.getAllByLabelText("名稱");
  await userEvent.clear(names[1]);
  await userEvent.type(names[1], "a");
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getAllByText("名稱不可空白或重複").length).toBeGreaterThan(0);
});

test("api key field is masked with a reveal toggle", async () => {
  setup({ a: { type: "openai_compat", base_url: "https://x/v1", api_key: "sk-test" } });
  const key = screen.getByLabelText("API key");
  expect(key).toHaveAttribute("type", "password");
  await userEvent.click(screen.getByRole("button", { name: "顯示" }));
  expect(screen.getByLabelText("API key")).toHaveAttribute("type", "text");
});

test("unknown keys survive edits and empty optional fields are dropped", async () => {
  const { onChange } = setup({
    a: { type: "openai_compat", base_url: "https://x/v1", timeout: 5 },
  });
  await userEvent.type(screen.getByLabelText("API key"), "k");
  expect(onChange).toHaveBeenLastCalledWith({
    a: { type: "openai_compat", base_url: "https://x/v1", timeout: 5, api_key: "k" },
  });
  await userEvent.clear(screen.getByLabelText("API key"));
  expect(onChange).toHaveBeenLastCalledWith({
    a: { type: "openai_compat", base_url: "https://x/v1", timeout: 5 },
  });
});

test("default model field writes model key", async () => {
  const { onChange } = setup({ a: { type: "openai_compat", base_url: "https://x/v1" } });
  await userEvent.type(screen.getByLabelText("預設模型"), "m1");
  expect(onChange).toHaveBeenLastCalledWith({
    a: { type: "openai_compat", base_url: "https://x/v1", model: "m1" },
  });
});

test("removing a provider propagates without it", async () => {
  const { onChange } = setup({ a: { type: "openai_compat", base_url: "https://x/v1" } });
  await userEvent.click(screen.getByRole("button", { name: "移除" }));
  expect(onChange).toHaveBeenLastCalledWith({});
});

test("non-openai types do not require base_url", async () => {
  const { onChange } = setup({ dry: { type: "fake" } });
  await userEvent.type(screen.getByLabelText("名稱"), "2");
  expect(onChange).toHaveBeenLastCalledWith({ dry2: { type: "fake" } });
});
