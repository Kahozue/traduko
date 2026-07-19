import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import type { ApiClient } from "../lib/api/client";
import type { TaskRecord, TaskTranslationDoc } from "../lib/api/types";
import { renderWithConnection } from "../test/helpers";
import { TranslationSettingsView } from "./TranslationSettingsView";

const translation: TaskTranslationDoc = {
  stage_type: "translate",
  target_language: "ja",
  style: "簡潔",
  prompt_override: "",
};

const task: TaskRecord = {
  schema_version: 1,
  id: "t1",
  project: "default",
  input_path: "/tmp/in.srt",
  profile: "subtitle-translate",
  name: null,
  status: "completed",
  stages: [
    {
      type: "translate",
      status: "completed",
      params: {},
      pause_after: false,
      artifacts: [],
      error: null,
    },
  ],
  created_at: "2026-07-16T10:00:00+00:00",
  updated_at: "2026-07-16T10:00:00+00:00",
  glossary: { global_ids: ["g1"], use_task: true, asr_mode: "auto" },
};

function setup(overrides: Partial<ApiClient> = {}, onOpenGlossary = vi.fn()) {
  const patchTaskTranslation = vi.fn().mockResolvedValue(translation);
  const retranslate = vi
    .fn()
    .mockResolvedValue({ queued: true, reset_from: "translate" });
  const api: Partial<ApiClient> = {
    showTask: vi.fn().mockResolvedValue(task),
    getTaskTranslation: vi.fn().mockResolvedValue(translation),
    patchTaskTranslation,
    retranslate,
    ...overrides,
  };
  renderWithConnection(
    <TranslationSettingsView
      project="default"
      taskId="t1"
      onBack={() => {}}
      onOpenGlossary={onOpenGlossary}
    />,
    { api },
  );
  return { patchTaskTranslation, retranslate, onOpenGlossary };
}

// The inputs render before the query resolves, so every test waits for the
// loaded value rather than the element.
async function loadedLanguageInput() {
  const input = await screen.findByLabelText("目標語言");
  await waitFor(() => expect(input).toHaveValue("ja"));
  return input;
}

test("loads the task's current translation settings", async () => {
  setup();
  expect(await loadedLanguageInput()).toHaveValue("ja");
  expect(screen.getByLabelText("風格")).toHaveValue("簡潔");
  expect(screen.getByLabelText("Prompt 覆寫")).toHaveValue("");
});

test("saving writes the edited fields back", async () => {
  const { patchTaskTranslation } = setup();
  const language = await loadedLanguageInput();
  await userEvent.clear(language);
  await userEvent.type(language, "ko");

  await userEvent.click(screen.getByRole("button", { name: "儲存" }));

  await waitFor(() =>
    expect(patchTaskTranslation).toHaveBeenCalledWith("default", "t1", {
      target_language: "ko",
      style: "簡潔",
      prompt_override: "",
    }),
  );
});

test("retranslate confirms before resetting downstream work", async () => {
  const { retranslate } = setup();
  await loadedLanguageInput();

  await userEvent.click(screen.getByRole("button", { name: "重新翻譯" }));

  expect(retranslate).not.toHaveBeenCalled();
  expect(await screen.findByText("重新翻譯會覆蓋既有編輯")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重新翻譯並執行" }));
  await waitFor(() => expect(retranslate).toHaveBeenCalledWith("default", "t1"));
});

test("the glossary summary links to the task glossary page", async () => {
  const { onOpenGlossary } = setup();
  await loadedLanguageInput();

  await userEvent.click(screen.getByRole("button", { name: "名詞表" }));

  expect(onOpenGlossary).toHaveBeenCalledTimes(1);
});
