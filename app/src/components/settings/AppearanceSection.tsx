import { useRef } from "react";
import type { KeyboardEvent } from "react";
import { t } from "../../i18n";
import { localeStore, useLocale, type Locale } from "../../lib/locale";
import { themeStore, useThemeMode, type ThemeMode } from "../../lib/theme";
import { Icon, type IconName } from "../icons";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

const OPTIONS: { mode: ThemeMode; icon: IconName; label: "theme.light" | "theme.dark" | "theme.system" }[] = [
  { mode: "light", icon: "sun", label: "theme.light" },
  { mode: "dark", icon: "moon", label: "theme.dark" },
  { mode: "system", icon: "monitor", label: "theme.system" },
];

const LOCALE_OPTIONS: { locale: Locale; label: "locale.zhTW" | "locale.en" | "locale.ja" }[] = [
  { locale: "zh-TW", label: "locale.zhTW" },
  { locale: "en", label: "locale.en" },
  { locale: "ja", label: "locale.ja" },
];

export function AppearanceSection() {
  const mode = useThemeMode();
  const activeIndex = OPTIONS.findIndex((option) => option.mode === mode);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const locale = useLocale();
  const localeIndex = LOCALE_OPTIONS.findIndex((option) => option.locale === locale);
  const localeRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: KeyboardEvent) {
    let delta = 0;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") delta = 1;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") delta = -1;
    else return;
    event.preventDefault();
    const next = (activeIndex + delta + OPTIONS.length) % OPTIONS.length;
    themeStore.setMode(OPTIONS[next].mode);
    refs.current[next]?.focus();
  }

  function onLocaleKeyDown(event: KeyboardEvent) {
    let delta = 0;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") delta = 1;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") delta = -1;
    else return;
    event.preventDefault();
    const next = (localeIndex + delta + LOCALE_OPTIONS.length) % LOCALE_OPTIONS.length;
    localeStore.setLocale(LOCALE_OPTIONS[next].locale);
    localeRefs.current[next]?.focus();
  }

  return (
    <Section title={t("settings.appearance")}>
      <SettingRow label={t("settings.theme")}>
        <div
          role="radiogroup"
          aria-label={t("settings.theme")}
          className={styles.segmented}
          onKeyDown={onKeyDown}
        >
          <span
            className={styles.segIndicator}
            style={{ transform: `translateX(${activeIndex * 100}%)` }}
            aria-hidden="true"
          />
          {OPTIONS.map((option, index) => (
            <button
              key={option.mode}
              type="button"
              role="radio"
              aria-checked={option.mode === mode}
              tabIndex={option.mode === mode ? 0 : -1}
              ref={(node) => {
                refs.current[index] = node;
              }}
              className={styles.segItem}
              onClick={() => themeStore.setMode(option.mode)}
            >
              <Icon name={option.icon} size={14} />
              <span>{t(option.label)}</span>
            </button>
          ))}
        </div>
      </SettingRow>
      <SettingRow label={t("settings.language")}>
        <div
          role="radiogroup"
          aria-label={t("settings.language")}
          className={styles.segmented}
          onKeyDown={onLocaleKeyDown}
        >
          <span
            className={styles.segIndicator}
            style={{ transform: `translateX(${localeIndex * 100}%)` }}
            aria-hidden="true"
          />
          {LOCALE_OPTIONS.map((option, index) => (
            <button
              key={option.locale}
              type="button"
              role="radio"
              aria-checked={option.locale === locale}
              tabIndex={option.locale === locale ? 0 : -1}
              ref={(node) => {
                localeRefs.current[index] = node;
              }}
              className={styles.segItem}
              onClick={() => localeStore.setLocale(option.locale)}
            >
              <span>{t(option.label)}</span>
            </button>
          ))}
        </div>
      </SettingRow>
    </Section>
  );
}
