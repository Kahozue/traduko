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
  // New rows start on the OpenAI preset: base_url, model and the model's
  // token ceilings are pre-filled but the row still needs a name, so it is
  // not yet a valid record.
  expect(onChange).toHaveBeenLastCalledWith(null);
  await userEvent.type(screen.getByLabelText("名稱"), "openai");
  expect(onChange).toHaveBeenLastCalledWith({
    openai: {
      type: "openai_compat",
      base_url: "https://api.openai.com/v1",
      model: "gpt-5.4-mini",
      context_window: 400000,
      max_output_tokens: 128000,
    },
  });
});

test("switching presets replaces auto-filled base_url, model and limits", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "新增供應商" }));
  // A fresh row carries the OpenAI pre-fill; picking another preset must
  // swap the fields, not leave the OpenAI values behind.
  await userEvent.selectOptions(screen.getByLabelText("供應商"), "gemini");
  await userEvent.type(screen.getByLabelText("名稱"), "g");
  expect(onChange).toHaveBeenLastCalledWith({
    g: {
      type: "gemini",
      base_url: "https://generativelanguage.googleapis.com/v1beta",
      model: "gemini-3.1-flash-lite",
      context_window: 1048576,
      max_output_tokens: 65536,
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
  // The hand-typed url and model survive; the limits from the initial
  // auto-fill stay untouched because the model was not replaced.
  expect(onChange).toHaveBeenLastCalledWith({
    ds: {
      type: "openai_compat",
      base_url: "https://my-proxy.local/v1",
      model: "my-model",
      context_window: 400000,
      max_output_tokens: 128000,
    },
  });
});

test("recognized model updates the token ceilings", async () => {
  const { onChange } = setup({ a: { type: "openai_compat", base_url: "https://x/v1" } });
  const modelInput = screen.getByLabelText("預設模型");
  await userEvent.clear(modelInput);
  await userEvent.type(modelInput, "glm-4.7-flash");
  expect(onChange).toHaveBeenLastCalledWith({
    a: {
      type: "openai_compat",
      base_url: "https://x/v1",
      model: "glm-4.7-flash",
      context_window: 200000,
      max_output_tokens: 131072,
    },
  });
});

test("non-numeric token ceiling blocks the draft with an error", async () => {
  const { onChange } = setup({ a: { type: "openai_compat", base_url: "https://x/v1" } });
  await userEvent.type(screen.getByLabelText("上下文視窗"), "abc");
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getByText("須為正整數")).toBeInTheDocument();
});

test("claude preset exposes the full field set with optional base_url", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "新增供應商" }));
  await userEvent.selectOptions(screen.getByLabelText("供應商"), "claude");
  await userEvent.type(screen.getByLabelText("名稱"), "c");
  await userEvent.type(screen.getByLabelText("API key"), "sk-ant");
  // The native adapter has a default endpoint, so clearing base_url stays
  // valid and simply drops the key.
  await userEvent.clear(screen.getByLabelText("API 位址（base_url）"));
  expect(onChange).toHaveBeenLastCalledWith({
    c: {
      type: "anthropic",
      model: "claude-haiku-4-5",
      context_window: 200000,
      max_output_tokens: 64000,
      api_key: "sk-ant",
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

test("default provider selector lists rows and reports the choice", async () => {
  const onChange = vi.fn();
  const onDefaultProvider = vi.fn();
  render(
    <ProvidersSection
      providers={{
        a: { type: "openai_compat", base_url: "https://a/v1" },
        b: { type: "openai_compat", base_url: "https://b/v1" },
      }}
      defaultProvider=""
      onChange={onChange}
      onDefaultProvider={onDefaultProvider}
    />,
  );
  const select = screen.getByLabelText("預設供應商");
  await userEvent.selectOptions(select, "b");
  expect(onDefaultProvider).toHaveBeenLastCalledWith("b");
});
