import { t } from "../../i18n";
import type { AudioConfigDoc } from "../../lib/api/types";
import { Section, SettingRow } from "./Section";

// Audio-domain pipeline defaults: the initial switch values a new audio task
// starts with (translate / diarize / dub). Existing tasks keep their own
// switches, so this only shapes what a fresh task looks like.
export function PipelineDefaultsSection({
  audio,
  onChange,
}: {
  audio: AudioConfigDoc;
  onChange: (value: AudioConfigDoc) => void;
}) {
  return (
    <Section
      title={t("settings.audio.pipeline.title")}
      hint={t("settings.audio.pipeline.hint")}
    >
      <SettingRow label={t("settings.audio.pipeline.translate")}>
        <input
          type="checkbox"
          aria-label={t("settings.audio.pipeline.translate")}
          checked={audio.translate_enabled}
          onChange={(event) =>
            onChange({ ...audio, translate_enabled: event.target.checked })
          }
        />
      </SettingRow>
      <SettingRow label={t("settings.audio.pipeline.diarize")}>
        <input
          type="checkbox"
          aria-label={t("settings.audio.pipeline.diarize")}
          checked={audio.diarize_enabled}
          onChange={(event) =>
            onChange({ ...audio, diarize_enabled: event.target.checked })
          }
        />
      </SettingRow>
      <SettingRow label={t("settings.audio.pipeline.dub")}>
        <input
          type="checkbox"
          aria-label={t("settings.audio.pipeline.dub")}
          checked={audio.dub_enabled}
          onChange={(event) =>
            onChange({ ...audio, dub_enabled: event.target.checked })
          }
        />
      </SettingRow>
    </Section>
  );
}
