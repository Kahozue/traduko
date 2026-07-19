import { useEffect, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import styles from "./ConfirmDialog.module.css";

// A minimal yes/no modal for actions that need a deliberate second step
// (destructive or overwriting). Structure mirrors CreateTaskDialog: an
// overlay-scrimmed dialog that traps focus and closes on Escape. The confirm
// button takes the danger outline when the action overwrites or destroys.
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  function onDialogKeyDown(event: ReactKeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button, input, select, [tabindex]:not([tabindex="-1"])',
    );
    if (!nodes || nodes.length === 0) return;
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

  return (
    <div className={styles.overlay}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        tabIndex={-1}
        onKeyDown={onDialogKeyDown}
      >
        <h2 id="confirm-dialog-title" className={styles.title}>
          {title}
        </h2>
        <p className={styles.body}>{body}</p>
        <div className={styles.footer}>
          <button type="button" className={styles.secondary} onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={danger ? styles.danger : styles.primary}
            disabled={busy}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
