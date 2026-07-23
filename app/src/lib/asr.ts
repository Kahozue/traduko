import type { MessageKey } from "../i18n";

// The single ASR engine roster shared by the new-task dialog and the task
// detail chip, so a new engine is added in one place. ids match core
// asr/engines.py; labels reuse the localized settings strings, keeping every
// surface in the active UI language instead of leaking hardcoded Chinese.
export const ASR_ENGINES: { id: string; label: MessageKey }[] = [
  { id: "faster_whisper", label: "settings.asr.engine.fasterWhisper" },
  { id: "macos_native", label: "settings.asr.engine.macos" },
  { id: "openai_whisper", label: "settings.asr.engine.openaiWhisper" },
  { id: "openai_gpt4o_diarize", label: "settings.asr.engine.gpt4oDiarize" },
  { id: "openai_gpt4o", label: "settings.asr.engine.gpt4o" },
  { id: "openai_gpt4o_mini", label: "settings.asr.engine.gpt4oMini" },
  { id: "cloud_custom", label: "settings.asr.engine.custom" },
];

export const ASR_ENGINE_LABEL: Record<string, MessageKey> = Object.fromEntries(
  ASR_ENGINES.map((engine) => [engine.id, engine.label]),
);
