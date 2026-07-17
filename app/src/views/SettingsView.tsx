import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../i18n";
import { useApi, useConnection } from "../lib/connection";
import type { CoreConfigDoc } from "../lib/api/types";
import { AppearanceSection } from "../components/settings/AppearanceSection";
import { BasicsSection } from "../components/settings/BasicsSection";
import { ProvidersSection } from "../components/settings/ProvidersSection";
import { ChannelsSection } from "../components/settings/ChannelsSection";
import { BotSection } from "../components/settings/BotSection";
import { SyncSection } from "../components/settings/SyncSection";
import styles from "../components/settings/settings.module.css";

function clone(config: CoreConfigDoc): CoreConfigDoc {
  // Config documents come from the JSON API, so a JSON round trip is a
  // faithful deep copy.
  return JSON.parse(JSON.stringify(config)) as CoreConfigDoc;
}

// An older core may return a config without newer sections (e.g. sync,
// discord_bot). Backfill them so the settings sections never read into
// undefined and blank the window; the user can still save and upgrade.
function normalize(config: CoreConfigDoc): CoreConfigDoc {
  const next = clone(config);
  if (!next.budget) next.budget = { task_usd_limit: null, monthly_usd_limit: null };
  if (!next.llm_providers) next.llm_providers = {};
  if (!next.notifications) next.notifications = { channels: [] };
  if (!next.notifications.channels) next.notifications.channels = [];
  if (!next.discord_bot) {
    next.discord_bot = {
      enabled: false,
      bot_token: "",
      bot_token_env: "",
      guild_id: "",
      channel_id: "",
      allowed_user_ids: [],
    };
  }
  if (!next.sync) {
    next.sync = {
      enabled: false,
      mode: "folder",
      folder_path: "",
      webdav_url: "",
      webdav_username: "",
      webdav_password: "",
      auto_interval_minutes: 0,
    };
  }
  return next;
}

export function SettingsView() {
  const api = useApi();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["config"], queryFn: () => api.getConfig() });
  const { data: syncStatus } = useQuery({
    queryKey: ["sync-status"],
    queryFn: () => api.getSyncStatus(),
  });

  const runSync = useMutation({
    mutationFn: () => api.runSync(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sync-status"] }),
  });
  const resolveConflict = useMutation({
    mutationFn: ({
      file,
      source,
      choice,
    }: {
      file: string;
      source: string;
      choice: "local" | "remote";
    }) => api.resolveSyncConflict(file, source, choice),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sync-status"] }),
  });

  const EMPTY_STATUS = {
    enabled: false,
    mode: "folder" as const,
    syncing: false,
    last_sync: null,
    last_result: null,
    conflicts: [],
    peers: [],
  };

  const [draft, setDraft] = useState<CoreConfigDoc | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [numbersValid, setNumbersValid] = useState(true);
  const [providersValid, setProvidersValid] = useState(true);
  const [channelsValid, setChannelsValid] = useState(true);
  const [botValid, setBotValid] = useState(true);
  const [syncValid, setSyncValid] = useState(true);

  useEffect(() => {
    if (data && draft === null) setDraft(normalize(data));
  }, [data, draft]);

  const dirty = useMemo(
    () =>
      draft !== null && data !== undefined && JSON.stringify(draft) !== JSON.stringify(data),
    [draft, data],
  );
  const projectValid = draft !== null && draft.default_project.trim() !== "";
  const valid =
    numbersValid && providersValid && channelsValid && botValid && syncValid && projectValid;

  const save = useMutation({
    mutationFn: () => api.saveConfig(draft as CoreConfigDoc),
    onSuccess: (saved) => {
      queryClient.setQueryData(["config"], saved);
      setDraft(normalize(saved));
      setResetKey((key) => key + 1);
      queryClient.invalidateQueries({ queryKey: ["budget"] });
    },
  });

  function discard() {
    if (data) setDraft(normalize(data));
    setNumbersValid(true);
    setProvidersValid(true);
    setChannelsValid(true);
    setBotValid(true);
    setSyncValid(true);
    setResetKey((key) => key + 1);
  }

  const statusText =
    conn.status === "ready"
      ? t("conn.ready")
      : conn.status === "connecting"
        ? t("conn.connecting")
        : t("conn.unavailable");

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>{t("settings.title")}</h1>

      <div className={styles.statusCard}>
        <div className={styles.statusPillRow}>
          <span className={styles.pill} data-status={conn.status}>
            <span className={styles.pillDot} aria-hidden="true" />
            {statusText}
          </span>
          <button type="button" className={styles.retry} onClick={conn.retry}>
            {t("conn.retry")}
          </button>
        </div>
        <div className={styles.statusItem}>
          <span className={styles.statusKey}>{t("settings.dataRoot")}</span>
          <span className={`${styles.statusValue} ${styles.statusMono}`}>
            {conn.dataRoot ?? "--"}
          </span>
        </div>
        <div className={styles.statusItem}>
          <span className={styles.statusKey}>{t("settings.coreUrl")}</span>
          <span className={`${styles.statusValue} ${styles.statusMono}`}>
            {conn.baseUrl ?? "--"}
          </span>
        </div>
      </div>

      <AppearanceSection />

      {draft && (
        <>
          <BasicsSection
            key={`basics-${resetKey}`}
            defaultProject={draft.default_project}
            budget={draft.budget}
            onDefaultProject={(value) =>
              setDraft((prev) => (prev ? { ...prev, default_project: value } : prev))
            }
            onBudget={(value) =>
              setDraft((prev) => (prev ? { ...prev, budget: value } : prev))
            }
            onValidity={setNumbersValid}
          />
          <ProvidersSection
            key={`providers-${resetKey}`}
            providers={draft.llm_providers}
            onChange={(value) => {
              setProvidersValid(value !== null);
              if (value !== null) {
                setDraft((prev) => (prev ? { ...prev, llm_providers: value } : prev));
              }
            }}
          />
          <ChannelsSection
            key={`channels-${resetKey}`}
            channels={draft.notifications.channels}
            onChange={(value) => {
              setChannelsValid(value !== null);
              if (value !== null) {
                setDraft((prev) =>
                  prev
                    ? { ...prev, notifications: { ...prev.notifications, channels: value } }
                    : prev,
                );
              }
            }}
            onTest={(channel) => api.testNotification(channel)}
          />
          <BotSection
            key={`bot-${resetKey}`}
            bot={draft.discord_bot}
            onChange={(value) => {
              setBotValid(value !== null);
              if (value !== null) {
                setDraft((prev) => (prev ? { ...prev, discord_bot: value } : prev));
              }
            }}
          />
          <SyncSection
            key={`sync-${resetKey}`}
            sync={draft.sync}
            status={syncStatus ?? EMPTY_STATUS}
            onChange={(value) => {
              setSyncValid(value !== null);
              if (value !== null) {
                setDraft((prev) => (prev ? { ...prev, sync: value } : prev));
              }
            }}
            onSyncNow={() => runSync.mutate()}
            onResolve={(file, source, choice) =>
              resolveConflict.mutate({ file, source, choice })
            }
          />
          {(dirty || save.isSuccess) && (
            <div className={styles.saveBar}>
              {dirty ? (
                <>
                  <span>{t("settings.dirty")}</span>
                  {save.isError && (
                    <span className={styles.saveError}>{t("settings.saveFailed")}</span>
                  )}
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={discard}
                  >
                    {t("settings.discard")}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!valid || save.isPending}
                    onClick={() => save.mutate()}
                  >
                    {t("settings.save")}
                  </button>
                </>
              ) : (
                <span className={styles.savedNote}>{t("settings.saved")}</span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
