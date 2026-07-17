import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t, type MessageKey } from "../i18n";
import { useApi, useConnection } from "../lib/connection";
import type { CoreConfigDoc } from "../lib/api/types";
import { AboutSection } from "../components/settings/AboutSection";
import { AgentSection } from "../components/settings/AgentSection";
import { AppearanceSection } from "../components/settings/AppearanceSection";
import { BasicsSection } from "../components/settings/BasicsSection";
import { AsrSection } from "../components/settings/AsrSection";
import { ProvidersSection } from "../components/settings/ProvidersSection";
import { ChannelsSection } from "../components/settings/ChannelsSection";
import { BotSection } from "../components/settings/BotSection";
import { SyncSection } from "../components/settings/SyncSection";
import styles from "../components/settings/settings.module.css";

// Tabs follow the information architecture in internal/design-language.md:
// one pipeline domain per tab, future domains (documents, comics, agent)
// slot in after "video"; integrations and about stay last.
const TABS = ["general", "video", "agent", "integrations", "about"] as const;
export type SettingsTab = (typeof TABS)[number];
type TabId = SettingsTab;

const TAB_LABELS: Record<TabId, MessageKey> = {
  general: "settings.tab.general",
  video: "settings.tab.video",
  agent: "settings.tab.agent",
  integrations: "settings.tab.integrations",
  about: "settings.tab.about",
};

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
  if (!next.mcp_servers) next.mcp_servers = {};
  // Mirror the core's confirmed-field migration (a v2-04 core sends servers
  // without it): already-enabled servers count as confirmed so the upgrade
  // does not unmount them, everything else starts unconfirmed. Applying the
  // same rule to both sides keeps dirty-comparison honest.
  for (const server of Object.values(next.mcp_servers)) {
    if (server.confirmed === undefined) server.confirmed = server.enabled;
  }
  if (!next.skills) next.skills = {};
  return next;
}

export function SettingsView({
  initialTab,
  onEditSkill,
}: {
  // Where to land when the view opens; the skill editor's back path uses
  // this to return to the agent tab.
  initialTab?: SettingsTab;
  onEditSkill?: (name: string) => void;
} = {}) {
  const api = useApi();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["config"], queryFn: () => api.getConfig() });
  const { data: syncStatus } = useQuery({
    queryKey: ["sync-status"],
    queryFn: () => api.getSyncStatus(),
  });
  const { data: mcpStatus } = useQuery({
    queryKey: ["mcp-status"],
    queryFn: () => api.getMcpStatus(),
    refetchInterval: 5000,
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
  const [tab, setTab] = useState<TabId>(initialTab ?? "general");
  const [numbersValid, setNumbersValid] = useState(true);
  const [providersValid, setProvidersValid] = useState(true);
  const [channelsValid, setChannelsValid] = useState(true);
  const [botValid, setBotValid] = useState(true);
  const [syncValid, setSyncValid] = useState(true);
  const [agentValid, setAgentValid] = useState(true);
  // Editing a skill navigates away and unmounts this view; with unsaved
  // draft edits that would silently discard them, so gate the navigation
  // behind an explicit confirmation.
  const [pendingEditSkill, setPendingEditSkill] = useState<string | null>(null);

  useEffect(() => {
    if (data && draft === null) setDraft(normalize(data));
  }, [data, draft]);

  // Compare against the normalized server config: backfilled sections
  // (added by newer app versions) must not count as unsaved edits.
  const dirty = useMemo(
    () =>
      draft !== null &&
      data !== undefined &&
      JSON.stringify(draft) !== JSON.stringify(normalize(data)),
    [draft, data],
  );
  const projectValid = draft !== null && draft.default_project.trim() !== "";
  const valid =
    numbersValid &&
    providersValid &&
    channelsValid &&
    botValid &&
    syncValid &&
    agentValid &&
    projectValid;

  // The save bar is visible from every tab, so point at the tab that holds
  // the failing fields instead of assuming the user can see them.
  const invalidTabs: TabId[] = [];
  if (!projectValid || !numbersValid || !providersValid) invalidTabs.push("general");
  if (!agentValid) invalidTabs.push("agent");
  if (!channelsValid || !botValid || !syncValid) invalidTabs.push("integrations");

  function onTabKeyDown(event: React.KeyboardEvent) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const next = TABS[(TABS.indexOf(tab) + delta + TABS.length) % TABS.length];
    setTab(next);
    document.getElementById(`settings-tab-${next}`)?.focus();
  }

  const save = useMutation({
    mutationFn: () => api.saveConfig(draft as CoreConfigDoc),
    onSuccess: (saved) => {
      queryClient.setQueryData(["config"], saved);
      setDraft(normalize(saved));
      setResetKey((key) => key + 1);
      queryClient.invalidateQueries({ queryKey: ["budget"] });
      // The core rebuilds its skills manager from the saved config, so the
      // list's enabled/confirmed flags change server side.
      queryClient.invalidateQueries({ queryKey: ["skills"] });
      // Saved mcp_servers only take effect once the core rebuilds its
      // connections; harmless when nothing is configured.
      void api
        .reloadMcp()
        .then(() => queryClient.invalidateQueries({ queryKey: ["mcp-status"] }))
        .catch(() => {});
    },
  });

  function discard() {
    if (data) setDraft(normalize(data));
    setNumbersValid(true);
    setProvidersValid(true);
    setChannelsValid(true);
    setBotValid(true);
    setSyncValid(true);
    setAgentValid(true);
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

      <div
        role="tablist"
        aria-label={t("settings.title")}
        className={styles.tabs}
        onKeyDown={onTabKeyDown}
      >
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`settings-tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`settings-panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            className={styles.tab}
            onClick={() => setTab(id)}
          >
            {t(TAB_LABELS[id])}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id="settings-panel-general"
        aria-labelledby="settings-tab-general"
        hidden={tab !== "general"}
        className={styles.panel}
      >
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
              onTest={(config) => api.testProvider(config, String(config.model ?? "") || undefined)}
            />
          </>
        )}
      </div>

      <div
        role="tabpanel"
        id="settings-panel-video"
        aria-labelledby="settings-tab-video"
        hidden={tab !== "video"}
        className={styles.panel}
      >
        <AsrSection />
      </div>

      <div
        role="tabpanel"
        id="settings-panel-agent"
        aria-labelledby="settings-tab-agent"
        hidden={tab !== "agent"}
        className={styles.panel}
      >
        {draft && (
          <AgentSection
            key={`agent-${resetKey}`}
            servers={draft.mcp_servers}
            status={mcpStatus ?? []}
            skills={draft.skills}
            onChange={(value) => {
              setAgentValid(value !== null);
              if (value !== null) {
                setDraft((prev) => (prev ? { ...prev, mcp_servers: value } : prev));
              }
            }}
            onSkillsChange={(value) =>
              setDraft((prev) => (prev ? { ...prev, skills: value } : prev))
            }
            onEditSkill={(name) => {
              if (dirty) setPendingEditSkill(name);
              else onEditSkill?.(name);
            }}
          />
        )}
      </div>

      <div
        role="tabpanel"
        id="settings-panel-integrations"
        aria-labelledby="settings-tab-integrations"
        hidden={tab !== "integrations"}
        className={styles.panel}
      >
        {draft && (
          <>
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
          </>
        )}
      </div>

      <div
        role="tabpanel"
        id="settings-panel-about"
        aria-labelledby="settings-tab-about"
        hidden={tab !== "about"}
        className={styles.panel}
      >
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
        <AboutSection />
      </div>

      {draft && (dirty || save.isSuccess) && (
        <div className={styles.saveBar}>
          {dirty ? (
            <>
              <span>{t("settings.dirty")}</span>
              {invalidTabs.length > 0 && (
                <span className={styles.saveError}>
                  {t("settings.invalidTabs") +
                    invalidTabs.map((id) => t(TAB_LABELS[id])).join("、")}
                </span>
              )}
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

      {pendingEditSkill !== null && (
        <div className={styles.scrim}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t("editor.skill.leaveTitle")}
            className={styles.confirmCard}
            onKeyDown={(event) => {
              if (event.key === "Escape") setPendingEditSkill(null);
            }}
          >
            <h3 className={styles.confirmTitle}>{t("editor.skill.leaveTitle")}</h3>
            <p className={styles.confirmIntro}>{t("editor.skill.leaveMessage")}</p>
            <div className={styles.confirmActions}>
              <button
                type="button"
                autoFocus
                className={styles.secondaryButton}
                onClick={() => setPendingEditSkill(null)}
              >
                {t("editor.leave.stay")}
              </button>
              <button
                type="button"
                className={styles.primaryButton}
                onClick={() => {
                  const name = pendingEditSkill;
                  setPendingEditSkill(null);
                  onEditSkill?.(name);
                }}
              >
                {t("editor.leave.discard")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
