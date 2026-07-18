import { localeStore } from "../lib/locale";
import { zhTW } from "./zh-TW";
import { en } from "./en";
import { ja } from "./ja";

export type MessageKey = keyof typeof zhTW;

const TABLES: Record<string, Record<MessageKey, string>> = {
  "zh-TW": zhTW,
  en,
  ja,
};

// Reads the active locale on every call; components re-render via the
// locale-keyed subtree remount in App, so no per-call subscription needed.
export function t(key: MessageKey): string {
  const table = TABLES[localeStore.getLocale()] ?? zhTW;
  return table[key] ?? zhTW[key];
}
