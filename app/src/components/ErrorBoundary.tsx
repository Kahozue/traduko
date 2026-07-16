import { Component, type ErrorInfo, type ReactNode } from "react";
import { t } from "../i18n";
import styles from "./ErrorBoundary.module.css";

interface State {
  error: Error | null;
}

// A crash in any view must not blank the whole window. This catches render
// errors, shows the message and offers a reload instead of a white screen.
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("view crashed:", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error === null) return this.props.children;
    return (
      <div className={styles.wrap}>
        <p className={styles.title}>{t("error.title")}</p>
        <pre className={styles.detail}>{this.state.error.message}</pre>
        <button
          type="button"
          className={styles.button}
          onClick={() => this.setState({ error: null })}
        >
          {t("error.retry")}
        </button>
      </div>
    );
  }
}
