import { useSyncExternalStore } from "react";

// UI language is a device-level preference like the theme: stored in
// localStorage, never in the core config.
export type Locale = "zh-TW" | "en" | "ja";

const STORAGE_KEY = "traduko.locale";
const LOCALES: Locale[] = ["zh-TW", "en", "ja"];

function readStored(): Locale {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value && (LOCALES as string[]).includes(value)) return value as Locale;
  } catch {
    // localStorage can throw in locked-down webviews; fall back to zh-TW.
  }
  return "zh-TW";
}

export class LocaleStore {
  private locale: Locale = readStored();
  private listeners = new Set<() => void>();

  getLocale = (): Locale => this.locale;

  setLocale(locale: Locale): void {
    if (locale === this.locale) return;
    this.locale = locale;
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      // A failed write is not fatal; the locale still applies this session.
    }
    for (const listener of this.listeners) listener();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
}

export const localeStore = new LocaleStore();

export function useLocale(): Locale {
  return useSyncExternalStore(localeStore.subscribe, localeStore.getLocale);
}
