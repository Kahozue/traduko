import { useId } from "react";
import { t } from "../../i18n";
import type { TranslationDomainDefaultsDoc } from "../../lib/api/types";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

// Per-domain translation defaults. A new task copies these into its own
// translate stage params at creation time, so editing them never disturbs
// tasks that already exist.
export function TranslationSection({
  defaults,
  onChange,
}: {
  defaults: TranslationDomainDefaultsDoc;
  onChange: (value: TranslationDomainDefaultsDoc) => void;
}) {
  const id = useId();
  return (
    <Section title={t("settings.translation.title")}>
      <SettingRow
        label={t("settings.translation.targetLanguage")}
        htmlFor={`${id}-language`}
      >
        <input
          id={`${id}-language`}
          className={styles.codeInput}
          value={defaults.target_language}
          onChange={(event) =>
            onChange({ ...defaults, target_language: event.target.value })
          }
        />
      </SettingRow>
      <SettingRow
        label={t("settings.translation.style")}
        htmlFor={`${id}-style`}
        description={t("settings.translation.styleDesc")}
      >
        <input
          id={`${id}-style`}
          className={styles.textInput}
          value={defaults.style}
          onChange={(event) => onChange({ ...defaults, style: event.target.value })}
        />
      </SettingRow>
      <SettingRow
        label={t("settings.translation.promptOverride")}
        htmlFor={`${id}-prompt`}
        description={t("settings.translation.promptOverrideDesc")}
      >
        <textarea
          id={`${id}-prompt`}
          className={styles.promptInput}
          rows={6}
          value={defaults.prompt_override}
          onChange={(event) =>
            onChange({ ...defaults, prompt_override: event.target.value })
          }
        />
      </SettingRow>
    </Section>
  );
}
