import { useRef, useState } from "react";
import { t } from "../../i18n";
import type { McpServerConfigDoc, McpServerStatus } from "../../lib/api/types";
import { Section } from "./Section";
import styles from "./settings.module.css";

interface Row {
  uid: number;
  name: string;
  config: McpServerConfigDoc;
  argsText: string;
}

const STATE_LABELS = {
  connected: "settings.mcp.state.connected",
  connecting: "settings.mcp.state.connecting",
  error: "settings.mcp.state.error",
  disabled: "settings.mcp.state.disabled",
} as const;

function normalize(rows: Row[]): Record<string, McpServerConfigDoc> | null {
  const out: Record<string, McpServerConfigDoc> = {};
  for (const row of rows) {
    const name = row.name.trim();
    if (!name || name in out) return null;
    if (row.config.transport === "stdio" && row.config.command.trim() === "") return null;
    if (row.config.transport === "http" && row.config.url.trim() === "") return null;
    out[name] = {
      ...row.config,
      args: row.argsText.split(/\s+/).filter(Boolean),
    };
  }
  return out;
}

export function AgentSection({
  servers,
  status,
  onChange,
}: {
  servers: Record<string, McpServerConfigDoc>;
  status: McpServerStatus[];
  onChange: (servers: Record<string, McpServerConfigDoc> | null) => void;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    Object.entries(servers).map(([name, config], index) => ({
      uid: index,
      name,
      config,
      argsText: (config.args ?? []).join(" "),
    })),
  );
  const nextUid = useRef(rows.length);
  const statusByName = new Map(status.map((row) => [row.name, row]));

  function apply(next: Row[]) {
    setRows(next);
    onChange(normalize(next));
  }

  function setRow(uid: number, patch: Partial<Row>) {
    apply(rows.map((row) => (row.uid === uid ? { ...row, ...patch } : row)));
  }

  function setField(uid: number, patch: Partial<McpServerConfigDoc>) {
    const row = rows.find((item) => item.uid === uid);
    if (!row) return;
    setRow(uid, { config: { ...row.config, ...patch } });
  }

  function add() {
    const uid = nextUid.current;
    nextUid.current += 1;
    apply([
      ...rows,
      {
        uid,
        name: "",
        config: {
          transport: "stdio",
          command: "",
          args: [],
          env: {},
          url: "",
          auth_token: "",
          enabled: true,
        },
        argsText: "",
      },
    ]);
  }

  const trimmedNames = rows.map((row) => row.name.trim());

  return (
    <Section
      title={t("settings.mcp")}
      hint={t("settings.mcp.hint")}
      action={
        <button
          type="button"
          className={`${styles.secondary} ${styles.headAction}`}
          onClick={add}
        >
          {t("settings.mcp.add")}
        </button>
      }
    >
      {rows.length === 0 && <p className={styles.emptyBox}>{t("settings.mcp.empty")}</p>}
      {rows.map((row) => {
        const name = row.name.trim();
        const nameInvalid =
          !name || trimmedNames.filter((candidate) => candidate === name).length > 1;
        const isStdio = row.config.transport === "stdio";
        const commandMissing = isStdio && row.config.command.trim() === "";
        const urlMissing = !isStdio && row.config.url.trim() === "";
        const serverStatus = statusByName.get(name);
        return (
          <div key={row.uid} className={styles.card}>
            <div className={styles.cardHeader}>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.mcp.name")}</span>
                <input
                  className={styles.input}
                  aria-label={t("settings.mcp.name")}
                  value={row.name}
                  onChange={(event) => setRow(row.uid, { name: event.target.value })}
                />
                {nameInvalid && (
                  <span className={styles.error}>{t("settings.mcp.nameInvalid")}</span>
                )}
              </label>
              {serverStatus && (
                <span className={styles.mcpState} data-state={serverStatus.state}>
                  {t(STATE_LABELS[serverStatus.state])}
                  {serverStatus.state === "connected" &&
                    ` · ${serverStatus.tools.length} ${t("settings.mcp.tools.unit")}`}
                </span>
              )}
              <button
                type="button"
                className={styles.secondary}
                onClick={() => apply(rows.filter((item) => item.uid !== row.uid))}
              >
                {t("settings.remove")}
              </button>
            </div>
            {serverStatus?.state === "error" && (
              <p className={styles.mcpError}>{serverStatus.error}</p>
            )}
            <div className={styles.fieldRow}>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.mcp.transport")}</span>
                <select
                  className={styles.input}
                  aria-label={t("settings.mcp.transport")}
                  value={row.config.transport}
                  onChange={(event) =>
                    setField(row.uid, {
                      transport: event.target.value as McpServerConfigDoc["transport"],
                    })
                  }
                >
                  <option value="stdio">stdio</option>
                  <option value="http">http</option>
                </select>
              </label>
              <label className={`${styles.checkItem} ${styles.toggleField}`}>
                <input
                  type="checkbox"
                  checked={row.config.enabled}
                  onChange={(event) => setField(row.uid, { enabled: event.target.checked })}
                />
                {t("settings.mcp.enabled")}
              </label>
            </div>
            {isStdio ? (
              <div className={styles.fieldRow}>
                <label className={styles.field}>
                  <span className={styles.label}>{t("settings.mcp.command")}</span>
                  <input
                    className={styles.input}
                    aria-label={t("settings.mcp.command")}
                    value={row.config.command}
                    onChange={(event) => setField(row.uid, { command: event.target.value })}
                  />
                  {commandMissing && (
                    <span className={styles.error}>{t("settings.mcp.commandRequired")}</span>
                  )}
                </label>
                <label className={styles.field}>
                  <span className={styles.label}>{t("settings.mcp.args")}</span>
                  <input
                    className={styles.input}
                    aria-label={t("settings.mcp.args")}
                    value={row.argsText}
                    onChange={(event) => setRow(row.uid, { argsText: event.target.value })}
                  />
                </label>
              </div>
            ) : (
              <div className={styles.fieldRow}>
                <label className={styles.field}>
                  <span className={styles.label}>{t("settings.mcp.url")}</span>
                  <input
                    className={styles.input}
                    aria-label={t("settings.mcp.url")}
                    value={row.config.url}
                    onChange={(event) => setField(row.uid, { url: event.target.value })}
                  />
                  {urlMissing && (
                    <span className={styles.error}>{t("settings.mcp.urlRequired")}</span>
                  )}
                </label>
                <label className={styles.field}>
                  <span className={styles.label}>{t("settings.mcp.token")}</span>
                  <input
                    className={styles.input}
                    type="password"
                    aria-label={t("settings.mcp.token")}
                    value={row.config.auth_token}
                    onChange={(event) =>
                      setField(row.uid, { auth_token: event.target.value })
                    }
                  />
                </label>
              </div>
            )}
          </div>
        );
      })}
    </Section>
  );
}
