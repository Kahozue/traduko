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

test("adding a provider prefills the openai preset and stays editable", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "新增供應商" }));
  // New rows start on the OpenAI preset: base_url and model are pre-filled
  // but the row still needs a name, so it is not yet a valid record.
  expect(onChange).toHaveBeenLastCalledWith(null);
  await userEvent.type(screen.getByLabelText("名稱"), "openai");
  expect(onChange).toHaveBeenLastCalledWith({
    openai: {
      type: "openai_compat",
      base_url: "https://api.openai.com/v1",
      model: "gpt-4o-mini",
    },
  });
});

test("switching presets replaces auto-filled base_url and model", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "新增供應商" }));
  // A fresh row carries the OpenAI pre-fill; picking another preset must
  // swap both fields, not leave the OpenAI values behind.
  await userEvent.selectOptions(screen.getByLabelText("供應商"), "gemini");
  await userEvent.type(screen.getByLabelText("名稱"), "g");
  expect(onChange).toHaveBeenLastCalledWith({
    g: {
      type: "gemini",
      base_url: "https://generativelanguage.googleapis.com/v1beta",
      model: "gemini-2.5-flash",
    },
  });
});

test("choosing a preset never clobbers hand-typed values", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "新增供應商" }));
  const urlInput = screen.getByLabelText("API 位址（base_url）");
  await userEvent.clear(urlInput);
  await userEvent.type(urlInput, "https://my-proxy.local/v1");
  const modelInput = screen.getByLabelText("預設模型");
  await userEvent.clear(modelInput);
  await userEvent.type(modelInput, "my-model");
  await userEvent.selectOptions(screen.getByLabelText("供應商"), "deepseek");
  await userEvent.type(screen.getByLabelText("名稱"), "ds");
  expect(onChange).toHaveBeenLastCalledWith({
    ds: {
      type: "openai_compat",
      base_url: "https://my-proxy.local/v1",
      model: "my-model",
    },
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

test("test button reports the probe outcome", async () => {
  const onChange = vi.fn();
  const onTest = vi.fn().mockResolvedValue({ ok: false, error: "http 401" });
  render(
    <ProvidersSection
      providers={{ a: { type: "openai_compat", base_url: "https://x/v1" } }}
      onChange={onChange}
      onTest={onTest}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "測試連線" }));
  expect(onTest).toHaveBeenCalledWith({ type: "openai_compat", base_url: "https://x/v1" });
  expect(await screen.findByText(/連線失敗.*http 401/)).toBeInTheDocument();
});
