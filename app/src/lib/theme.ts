import { useSyncExternalStore } from "react";

// The user picks one of three modes; "system" defers to the OS preference
// and keeps tracking it live, the other two pin the theme regardless.
export type ThemeMode = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "traduko.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function readStored(): ThemeMode {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "light" || value === "dark" || value === "system") return value;
  } catch {
    // localStorage can throw in locked-down webviews; fall back to system.
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return typeof matchMedia === "function" && matchMedia(DARK_QUERY).matches;
}

// Keep the native window chrome (titlebar) on the same theme as the
// webview. Passing null hands control back to the OS for system mode.
// Outside Tauri (tests, plain browser) this is a no-op.
async function applyNativeTheme(mode: ThemeMode): Promise<void> {
  if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().setTheme(mode === "system" ? null : mode);
  } catch {
    // Native chrome theming is cosmetic; the webview theme already applied.
  }
}

export class ThemeStore {
  private mode: ThemeMode = "system";
  private listeners = new Set<() => void>();
  private mediaQuery: MediaQueryList | null = null;
  private onMediaChange = () => this.apply();

  init(): void {
    this.mode = readStored();
    this.apply();
    this.syncMediaListener();
  }

  getMode = (): ThemeMode => this.mode;

  getResolved = (): ResolvedTheme => {
    if (this.mode === "system") return systemPrefersDark() ? "dark" : "light";
    return this.mode;
  };

  setMode(mode: ThemeMode): void {
    if (mode === this.mode) return;
    this.mode = mode;
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // A failed write is not fatal; the mode still applies for this session.
    }
    this.apply();
    this.syncMediaListener();
    for (const listener of this.listeners) listener();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private apply(): void {
    if (typeof document === "undefined") return;
    document.documentElement.dataset.theme = this.getResolved();
    void applyNativeTheme(this.mode);
  }

  // Only listen to the OS preference while in system mode; a pinned theme
  // must ignore the media query entirely.
  private syncMediaListener(): void {
    if (typeof matchMedia !== "function") return;
    const wantsListener = this.mode === "system";
    if (wantsListener && !this.mediaQuery) {
      this.mediaQuery = matchMedia(DARK_QUERY);
      this.mediaQuery.addEventListener("change", this.onMediaChange);
    } else if (!wantsListener && this.mediaQuery) {
      this.mediaQuery.removeEventListener("change", this.onMediaChange);
      this.mediaQuery = null;
    }
  }
}

export const themeStore = new ThemeStore();

export function useThemeMode(): ThemeMode {
  return useSyncExternalStore(themeStore.subscribe, themeStore.getMode);
}
