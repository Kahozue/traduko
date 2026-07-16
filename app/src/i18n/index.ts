import { zhTW } from "./zh-TW";

export type MessageKey = keyof typeof zhTW;

export function t(key: MessageKey): string {
  return zhTW[key];
}
