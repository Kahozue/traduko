import { useState } from "react";
import { t } from "../../i18n";
import type { SyncConfigDoc, SyncStatus, TaskStatus } from "../../lib/api/types";
import styles from "./settings.module.css";

export function SyncSection({
  sync,
  status,
  onChange,
  onSyncNow,
  onResolve,
}: {
  sync: SyncConfigDoc;
  status: SyncStatus;
  onChange: (value: SyncConfigDoc | null) => void;
  onSyncNow: () => void;
  onResolve: (file: string, source: string, choice: "local" | "remote") => void;
}) {
  const [reveal, setReveal] = useState(false);
  const [enabled, setEnabled] = useState(sync.enabled);
  const [mode, setMode] = useState<SyncConfigDoc["mode"]>(sync.mode);
  const [folder, setFolder] = useState(sync.folder_path);
  const [url, setUrl] = useState(sync.webdav_url);
  const [user, setUser] = useState(sync.webdav_username);
  const [password, setPassword] = useState(sync.webdav_password);
  const [intervalText, setIntervalText] = useState(String(sync.auto_interval_minutes));

  function push(
    next: {
      enabled?: boolean;
      mode?: SyncConfigDoc["mode"];
      folder?: string;
      url?: string;
      user?: string;
      password?: string;
      interval?: string;
    } = {},
  ) {
    const on = next.enabled ?? enabled;
    const mo = next.mode ?? mode;
    const fo = (next.folder ?? folder).trim();
    const ur = (next.url ?? url).trim();
    const interval = next.interval ?? intervalText;
    const intervalValid = /^\d+$/.test(interval.trim());
    const folderValid = !on || mo !== "folder" || fo !== "";
    const webdavValid = !on || mo !== "webdav" || ur !== "";
    if (!intervalValid || !folderValid || !webdavValid) {
      onChange(null);
      return;
    }
    onChange({
      ...sync,
      enabled: on,
      mode: mo,
      folder_path: next.folder ?? folder,
      webdav_url: next.url ?? url,
      webdav_username: next.user ?? user,
      webdav_password: next.password ?? password,
      auto_interval_minutes: Number(interval.trim()),
    });
  }

  const folderInvalid = enabled && mode === "folder" && folder.trim() === "";
  const webdavInvalid = enabled && mode === "webdav" && url.trim() === "";
  const intervalInvalid = !/^\d+$/.test(intervalText.trim());

  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>{t("settings.sync")}</h2>
        <button
          type="button"
          className={styles.secondary}
          disabled={status.syncing}
          onClick={onSyncNow}
        >
          {status.syncing ? t("settings.sync.syncing") : t("settings.sync.now")}
        </button>
      </div>
      <p className={styles.empty}>{t("settings.sync.restartHint")}</p>

      <label className={styles.checkItem}>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => {
            setEnabled(event.target.checked);
            push({ enabled: event.target.checked });
          }}
        />
        {t("settings.sync.enabled")}
      </label>

      <div className={styles.fieldRow}>
        <label className={styles.field}>
          <span className={styles.label}>{t("settings.sync.mode")}</span>
          <select
            className={styles.input}
            value={mode}
            onChange={(event) => {
              const value = event.target.value as SyncConfigDoc["mode"];
              setMode(value);
              push({ mode: value });
            }}
            aria-label={t("settings.sync.mode")}
          >
            <option value="folder">{t("settings.sync.mode.folder")}</option>
            <option value="webdav">{t("settings.sync.mode.webdav")}</option>
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.label}>{t("settings.sync.interval")}</span>
          <input
            className={styles.input}
            inputMode="numeric"
            value={intervalText}
            onChange={(event) => {
              setIntervalText(event.target.value);
              push({ interval: event.target.value });
            }}
            aria-label={t("settings.sync.interval")}
          />
          {intervalInvalid && (
            <span className={styles.error}>{t("settings.sync.intervalInvalid")}</span>
          )}
        </label>
      </div>

      {mode === "folder" ? (
        <label className={styles.field}>
          <span className={styles.label}>{t("settings.sync.folderPath")}</span>
          <input
            className={styles.input}
            value={folder}
            onChange={(event) => {
              setFolder(event.target.value);
              push({ folder: event.target.value });
            }}
            aria-label={t("settings.sync.folderPath")}
          />
          {folderInvalid && (
            <span className={styles.error}>{t("settings.sync.folderRequired")}</span>
          )}
        </label>
      ) : (
        <>
          <label className={styles.field}>
            <span className={styles.label}>{t("settings.sync.webdavUrl")}</span>
            <input
              className={styles.input}
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                push({ url: event.target.value });
              }}
              aria-label={t("settings.sync.webdavUrl")}
            />
            {webdavInvalid && (
              <span className={styles.error}>{t("settings.sync.webdavRequired")}</span>
            )}
          </label>
          <div className={styles.fieldRow}>
            <label className={styles.field}>
              <span className={styles.label}>{t("settings.sync.webdavUser")}</span>
              <input
                className={styles.input}
                value={user}
                onChange={(event) => {
                  setUser(event.target.value);
                  push({ user: event.target.value });
                }}
                aria-label={t("settings.sync.webdavUser")}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>{t("settings.sync.webdavPassword")}</span>
              <span className={styles.inline}>
                <input
                  className={styles.input}
                  type={reveal ? "text" : "password"}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    push({ password: event.target.value });
                  }}
                  aria-label={t("settings.sync.webdavPassword")}
                />
                <button
                  type="button"
                  className={styles.secondary}
                  onClick={() => setReveal((value) => !value)}
                >
                  {reveal ? t("settings.hide") : t("settings.reveal")}
                </button>
              </span>
            </label>
          </div>
        </>
      )}

      {status.last_sync && (
        <p className={styles.empty}>
          {t("settings.sync.lastSync")}
          {status.last_sync}
          {status.last_result && !status.last_result.ok
            ? `｜${t("settings.sync.lastFailed")}${status.last_result.error ?? ""}`
            : ""}
        </p>
      )}

      {status.conflicts.length > 0 && (
        <div className={styles.card}>
          <span className={styles.label}>{t("settings.sync.conflicts")}</span>
          {status.conflicts.map((conflict) => (
            <div
              className={styles.conflictRow}
              key={`${conflict.file}:${conflict.source}`}
            >
              <span className={styles.conflictValue}>{conflict.source}</span>
              <span className={styles.label}>{t("settings.sync.local")}</span>
              <span className={styles.conflictValue}>{conflict.local.target}</span>
              <span className={styles.label}>{t("settings.sync.remote")}</span>
              <span className={styles.conflictValue}>{conflict.remote.target}</span>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => onResolve(conflict.file, conflict.source, "local")}
              >
                {t("settings.sync.keepLocal")}
              </button>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => onResolve(conflict.file, conflict.source, "remote")}
              >
                {t("settings.sync.useRemote")}
              </button>
            </div>
          ))}
        </div>
      )}

      {status.peers.length > 0 && (
        <div className={styles.card}>
          <span className={styles.label}>{t("settings.sync.peers")}</span>
          {status.peers.map((peer) => (
            <div key={peer.machine}>
              <div className={styles.peerMachine}>{peer.machine}</div>
              {peer.tasks.map((task) => (
                <div className={styles.peerTask} key={task.id}>
                  {task.name || task.id}｜{t(`status.${task.status as TaskStatus}`)}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
