import { t } from "../../i18n";
import { Section, SettingRow } from "./Section";

// Per-domain pipeline defaults: the initial switch values a new task of that
// domain starts with. Existing tasks keep their own switches, so this only
// shapes what a fresh task looks like.
//
// Each domain tab renders its own copy (design language 1.2: a shared engine
// is still presented separately per domain), and a domain only shows the
// switches it has -- a document has no recording, so no speaker separation.

// The switch keys a domain can carry, in display order.
const SWITCH_ORDER = ["translate", "diarize", "dub"] as const;

type SwitchKey = (typeof SWITCH_ORDER)[number];

const FIELD_OF: Record<SwitchKey, string> = {
  translate: "translate_enabled",
  diarize: "diarize_enabled",
  dub: "dub_enabled",
};

const LABEL_OF: Record<SwitchKey, Parameters<typeof t>[0]> = {
  translate: "settings.pipeline.translate",
  diarize: "settings.pipeline.diarize",
  dub: "settings.pipeline.dub",
};

export function PipelineDefaultsSection<T extends Record<string, unknown>>({
  value,
  switches,
  onChange,
}: {
  value: T;
  switches: readonly SwitchKey[];
  onChange: (next: T) => void;
}) {
  const shown = SWITCH_ORDER.filter((name) => switches.includes(name));
  return (
    <Section
      title={t("settings.pipeline.title")}
      hint={t("settings.pipeline.hint")}
    >
      {shown.map((name) => {
        const field = FIELD_OF[name];
        const label = t(LABEL_OF[name]);
        return (
          <SettingRow key={name} label={label}>
            <input
              type="checkbox"
              aria-label={label}
              checked={value[field] === true}
              onChange={(event) =>
                onChange({ ...value, [field]: event.target.checked })
              }
            />
          </SettingRow>
        );
      })}
    </Section>
  );
}
