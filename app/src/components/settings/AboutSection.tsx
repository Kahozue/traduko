import { useEffect, useState } from "react";
import { t } from "../../i18n";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

const REPO_URL = "https://github.com/Kahozue/traduko";

export function AboutSection() {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    // App version only exists inside the Tauri shell; jsdom and plain-browser
    // dev show a dash instead.
    if (!("__TAURI_INTERNALS__" in window)) return;
    void import("@tauri-apps/api/app").then(async ({ getVersion }) => {
      setVersion(await getVersion());
    });
  }, []);

  return (
    <Section title={t("settings.about")}>
      <div className={styles.aboutBrand}>
        <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
          <path
            fill="currentColor"
            d="M12 2.5l2.6 6.05 6.56.56-4.98 4.32 1.5 6.41L12 16.43l-5.68 3.41 1.5-6.41-4.98-4.32 6.56-.56z"
          />
        </svg>
        <span className={styles.aboutName}>Traduko</span>
      </div>
      <SettingRow label={t("settings.about.version")}>
        <span className={styles.aboutValue}>{version ?? "--"}</span>
      </SettingRow>
      <SettingRow label={t("settings.about.repo")}>
        <span className={`${styles.aboutValue} ${styles.aboutMono}`}>{REPO_URL}</span>
      </SettingRow>
    </Section>
  );
}
