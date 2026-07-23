import type { KeyboardEvent as ReactKeyboardEvent } from "react";

// Keep Tab focus inside a modal dialog: from the last focusable control Tab
// wraps to the first, and Shift+Tab from the first wraps to the last, so a
// keyboard user never falls out of the dialog. CreateTaskDialog established
// this contract; every modal shares this one implementation to stay in step.
// Disabled controls are excluded — they are never the real boundary.
const FOCUSABLE =
  'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function trapTab(
  event: ReactKeyboardEvent,
  container: HTMLElement | null,
): void {
  if (event.key !== "Tab" || !container) return;
  const nodes = container.querySelectorAll<HTMLElement>(FOCUSABLE);
  if (nodes.length === 0) return;
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
