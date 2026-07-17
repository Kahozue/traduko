import { useRef, useState } from "react";
import { t } from "../../i18n";
import { eventTypeLabel } from "../../lib/labels";
import type { ChannelConfigDoc, EventType, NotifyTestResult } from "../../lib/api/types";
import { Section } from "./Section";
import styles from "./settings.module.css";

const ALL_EVENT_TYPES: EventType[] = [
  "task_started",
  "stage_started",
  "stage_progress",
  "stage_completed",
  "task_waiting_review",
  "task_completed",
  "task_failed",
  "task_canceled",
  "task_paused",
  "budget_warning",
  "budget_exceeded",
  "agent_round",
];

// Mirrors DEFAULT_EVENTS / EMAIL_DEFAULT_EVENTS in core notify.py.
const DEFAULT_EVENTS: EventType[] = ALL_EVENT_TYPES.filter(
  (type) => type !== "stage_progress" && type !== "agent_round",
);
const EMAIL_DEFAULT_EVENTS: EventType[] = [
  "task_completed",
  "task_failed",
  "budget_warning",
  "budget_exceeded",
];

const CHANNEL_TYPES = ["discord", "email", "webhook"] as const;

interface Row {
  uid: number;
  config: ChannelConfigDoc;
  toAddrsText: string;
  portText: string;
}

function parseAddrs(text: string): string[] {
  return text
    .split(",")
    .map((piece) => piece.trim())
    .filter(Boolean);
}

function toRow(config: ChannelConfigDoc, uid: number): Row {
  return {
    uid,
    config,
    toAddrsText: ((config.to_addrs as string[] | undefined) ?? []).join(", "),
    portText: config.smtp_port === undefined ? "" : String(config.smtp_port),
  };
}

function rowValid(row: Row): boolean {
  const type = String(row.config.type ?? "");
  if (type === "discord") return String(row.config.webhook_url ?? "").trim() !== "";
  if (type === "webhook") return String(row.config.url ?? "").trim() !== "";
  if (type === "email") {
    const portOk = row.portText.trim() === "" || /^\d+$/.test(row.portText.trim());
    return (
      String(row.config.smtp_host ?? "").trim() !== "" &&
      String(row.config.from_addr ?? "").trim() !== "" &&
      parseAddrs(row.toAddrsText).length > 0 &&
      portOk
    );
  }
  return true; // hand-written unknown types pass through untouched
}

function toConfig(row: Row): ChannelConfigDoc {
  if (String(row.config.type ?? "") !== "email") return row.config;
  const config: ChannelConfigDoc = { ...row.config, to_addrs: parseAddrs(row.toAddrsText) };
  const port = row.portText.trim();
  if (port === "") delete config.smtp_port;
  else config.smtp_port = Number(port);
  return config;
}

function normalize(rows: Row[]): ChannelConfigDoc[] | null {
  if (rows.some((row) => !rowValid(row))) return null;
  return rows.map(toConfig);
}

export function ChannelsSection({
  channels,
  onChange,
  onTest,
}: {
  channels: ChannelConfigDoc[];
  onChange: (channels: ChannelConfigDoc[] | null) => void;
  onTest: (channel: ChannelConfigDoc) => Promise<NotifyTestResult>;
}) {
  const [rows, setRows] = useState<Row[]>(() => channels.map(toRow));
  const nextUid = useRef(rows.length);
  const [tests, setTests] = useState<Record<number, "pending" | NotifyTestResult>>({});

  function apply(next: Row[]) {
    setRows(next);
    onChange(normalize(next));
  }

  function setRow(uid: number, patch: Partial<Row>) {
    apply(rows.map((row) => (row.uid === uid ? { ...row, ...patch } : row)));
  }

  function setField(uid: number, key: string, value: string) {
    const row = rows.find((item) => item.uid === uid);
    if (!row) return;
    const config = { ...row.config, [key]: value };
    if (value === "" && ["username", "password", "password_env"].includes(key)) {
      delete config[key];
    }
    setRow(uid, { config });
  }

  function add() {
    const uid = nextUid.current;
    nextUid.current += 1;
    apply([...rows, toRow({ type: "discord" }, uid)]);
  }

  function changeType(uid: number, type: string) {
    const row = rows.find((item) => item.uid === uid);
    if (!row) return;
    const config: ChannelConfigDoc =
      row.config.events === undefined ? { type } : { type, events: row.config.events };
    apply(
      rows.map((item) =>
        item.uid === uid ? { ...item, config, toAddrsText: "", portText: "" } : item,
      ),
    );
  }

  function toggleCustomEvents(uid: number, on: boolean) {
    const row = rows.find((item) => item.uid === uid);
    if (!row) return;
    const config = { ...row.config };
    if (on) {
      config.events =
        String(config.type) === "email" ? [...EMAIL_DEFAULT_EVENTS] : [...DEFAULT_EVENTS];
    } else {
      delete config.events;
    }
    setRow(uid, { config });
  }

  function toggleEvent(uid: number, type: EventType) {
    const row = rows.find((item) => item.uid === uid);
    if (!row) return;
    const current = (row.config.events as string[] | undefined) ?? [];
    const events = current.includes(type)
      ? current.filter((item) => item !== type)
      : [...current, type];
    setRow(uid, { config: { ...row.config, events } });
  }

  async function runTest(uid: number) {
    const row = rows.find((item) => item.uid === uid);
    if (!row || !rowValid(row)) return;
    setTests((prev) => ({ ...prev, [uid]: "pending" }));
    try {
      const result = await onTest(toConfig(row));
      setTests((prev) => ({ ...prev, [uid]: result }));
    } catch (error) {
      setTests((prev) => ({ ...prev, [uid]: { ok: false, error: String(error) } }));
    }
  }

  function textField(row: Row, key: string, label: string, masked = false) {
    return (
      <label className={styles.field}>
        <span className={styles.label}>{label}</span>
        <input
          className={styles.input}
          type={masked ? "password" : "text"}
          value={String(row.config[key] ?? "")}
          onChange={(event) => setField(row.uid, key, event.target.value)}
        />
      </label>
    );
  }

  return (
    <Section
      title={t("settings.channels")}
      action={
        <button
          type="button"
          className={`${styles.secondary} ${styles.headAction}`}
          onClick={add}
        >
          {t("settings.addChannel")}
        </button>
      }
    >
      {rows.length === 0 && <p className={styles.emptyBox}>{t("settings.channelsEmpty")}</p>}
      {rows.map((row) => {
        const type = String(row.config.type ?? "");
        const custom = Array.isArray(row.config.events);
        const testState = tests[row.uid];
        return (
          <div key={row.uid} className={styles.card}>
            <div className={styles.cardHeader}>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.channelType")}</span>
                <select
                  className={styles.input}
                  value={type}
                  onChange={(event) => changeType(row.uid, event.target.value)}
                >
                  {CHANNEL_TYPES.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                  {!CHANNEL_TYPES.includes(type as (typeof CHANNEL_TYPES)[number]) && (
                    <option value={type}>{type}</option>
                  )}
                </select>
              </label>
              <button
                type="button"
                className={styles.secondary}
                disabled={!rowValid(row) || testState === "pending"}
                onClick={() => runTest(row.uid)}
              >
                {testState === "pending" ? t("settings.testing") : t("settings.sendTest")}
              </button>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => apply(rows.filter((item) => item.uid !== row.uid))}
              >
                {t("settings.remove")}
              </button>
            </div>
            {!rowValid(row) && (
              <span className={styles.error}>{t("settings.requiredMissing")}</span>
            )}
            {testState && testState !== "pending" && (
              <div className={testState.ok ? styles.testResult : styles.testError}>
                {testState.ok
                  ? t("settings.testOk")
                  : `${t("settings.testFailedPrefix")}${testState.error ?? ""}`}
              </div>
            )}
            {type === "discord" && textField(row, "webhook_url", t("settings.webhookUrl"))}
            {type === "webhook" && textField(row, "url", t("settings.url"))}
            {type === "email" && (
              <>
                <div className={styles.fieldRow}>
                  {textField(row, "smtp_host", t("settings.smtpHost"))}
                  <label className={styles.field}>
                    <span className={styles.label}>{t("settings.smtpPort")}</span>
                    <input
                      className={styles.input}
                      inputMode="numeric"
                      placeholder="587"
                      value={row.portText}
                      onChange={(event) => setRow(row.uid, { portText: event.target.value })}
                    />
                  </label>
                </div>
                {textField(row, "from_addr", t("settings.fromAddr"))}
                <label className={styles.field}>
                  <span className={styles.label}>{t("settings.toAddrs")}</span>
                  <input
                    className={styles.input}
                    value={row.toAddrsText}
                    onChange={(event) => setRow(row.uid, { toAddrsText: event.target.value })}
                  />
                </label>
                <div className={styles.fieldRow}>
                  {textField(row, "username", t("settings.username"))}
                  {textField(row, "password", t("settings.password"), true)}
                  {textField(row, "password_env", t("settings.passwordEnv"))}
                </div>
              </>
            )}
            <label className={styles.checkItem}>
              <input
                type="checkbox"
                checked={custom}
                onChange={(event) => toggleCustomEvents(row.uid, event.target.checked)}
              />
              {t("settings.customEvents")}
            </label>
            {!custom && <p className={styles.empty}>{t("settings.customEventsHint")}</p>}
            {custom && (
              <div className={styles.checkGrid}>
                {ALL_EVENT_TYPES.map((eventType) => (
                  <label key={eventType} className={styles.checkItem}>
                    <input
                      type="checkbox"
                      checked={((row.config.events as string[]) ?? []).includes(eventType)}
                      onChange={() => toggleEvent(row.uid, eventType)}
                    />
                    {eventTypeLabel(eventType)}
                  </label>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </Section>
  );
}
