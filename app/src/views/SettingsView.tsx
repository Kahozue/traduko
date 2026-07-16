import { t } from "../i18n";
import { useConnection } from "../lib/connection";
import styles from "./SettingsView.module.css";

export function SettingsView() {
  const conn = useConnection();
  return (
    <div>
      <h1 className={styles.title}>{t("settings.title")}</h1>
      <div className={styles.card}>
        <dl className={styles.list}>
          <div className={styles.row}>
            <dt>{t("settings.dataRoot")}</dt>
            <dd className={styles.mono}>{conn.dataRoot ?? "--"}</dd>
          </div>
          <div className={styles.row}>
            <dt>{t("settings.coreUrl")}</dt>
            <dd className={styles.mono}>{conn.baseUrl ?? "--"}</dd>
          </div>
          <div className={styles.row}>
            <dt>{t("settings.status")}</dt>
            <dd>
              {conn.status === "ready"
                ? t("conn.ready")
                : conn.status === "connecting"
                  ? t("conn.connecting")
                  : t("conn.unavailable")}
              <button type="button" className={styles.retry} onClick={conn.retry}>
                {t("conn.retry")}
              </button>
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
