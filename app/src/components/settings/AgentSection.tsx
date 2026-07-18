import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../../i18n";
import { ApiError } from "../../lib/api/client";
import type {
  McpServerConfigDoc,
  McpServerStatus,
  McpToolInfo,
  SkillConfigDoc,
} from "../../lib/api/types";
import { useApi } from "../../lib/connection";
import { Section } from "./Section";
import styles from "./settings.module.css";

interface Row {
  uid: number;
  name: string;
  config: McpServerConfigDoc;
  argsText: string;
}

// The confirmation card is the tool-poisoning gate: flipping an unconfirmed
// item on first shows the user exactly what would enter the agent (an MCP
// server's tool list, a skill's full SKILL.md). Confirming writes
// enabled+confirmed into the DRAFT; the save bar stays the commit point.
type PendingConfirm =
  | { kind: "mcp"; uid: number; name: string }
  | { kind: "skill"; name: string };

const STATE_LABELS = {
  connected: "settings.mcp.state.connected",
  connecting: "settings.mcp.state.connecting",
  error: "settings.mcp.state.error",
  disabled: "settings.mcp.state.disabled",
} as const;

// Mirrors the core's skill name rule (skillhub._name_errors).
const SKILL_NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

function skillNameValid(name: string): boolean {
  return name.length > 0 && name.length <= 64 && SKILL_NAME_RE.test(name);
}

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
  skills,
  onChange,
  onSkillsChange,
  onEditSkill,
}: {
  servers: Record<string, McpServerConfigDoc>;
  status: McpServerStatus[];
  skills: Record<string, SkillConfigDoc>;
  onChange: (servers: Record<string, McpServerConfigDoc> | null) => void;
  onSkillsChange: (skills: Record<string, SkillConfigDoc>) => void;
  onEditSkill?: (name: string) => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Row[]>(() =>
    Object.entries(servers).map(([name, config], index) => ({
      uid: index,
      name,
      config,
      argsText: (config.args ?? []).join(" "),
    })),
  );
  const nextUid = useRef(rows.length);
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const [newSkillName, setNewSkillName] = useState("");
  // The create form is a transient row at the top of the list, opened from
  // the section header so creation sits next to import instead of dangling
  // under the list.
  const [creating, setCreating] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const statusByName = new Map(status.map((row) => [row.name, row]));

  const skillList = useQuery({
    queryKey: ["skills"],
    queryFn: () => api.listSkills(),
  });

  const createSkill = useMutation({
    mutationFn: (name: string) => api.createSkill(name),
    onSuccess: () => {
      setNewSkillName("");
      setCreating(false);
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });

  const importSkill = useMutation({
    mutationFn: (content: string) => api.importSkill(content),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["skills"] }),
  });

  const deleteSkill = useMutation({
    // A config-only row ("missing" on disk) has nothing to delete server
    // side; swallowing the 404 lets the same button clear both cases.
    mutationFn: async (name: string) => {
      try {
        await api.deleteSkill(name);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      }
    },
    onSuccess: (_data, name) => {
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      if (name in skills) {
        const next = { ...skills };
        delete next[name];
        onSkillsChange(next);
      }
    },
  });

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
          // New servers start disabled and unconfirmed: flipping the
          // toggle routes through the confirmation card. Sending confirmed
          // explicitly also keeps the core's legacy migration (enabled
          // without confirmed => confirmed) from waving the gate through.
          enabled: false,
          confirmed: false,
        },
        argsText: "",
      },
    ]);
  }

  function toggleServer(row: Row, on: boolean) {
    if (on && !row.config.confirmed) {
      setPending({ kind: "mcp", uid: row.uid, name: row.name.trim() });
      return;
    }
    setField(row.uid, { enabled: on });
  }

  function toggleSkill(name: string, on: boolean) {
    const existing = skills[name];
    if (on && !existing?.confirmed) {
      setPending({ kind: "skill", name });
      return;
    }
    onSkillsChange({
      ...skills,
      [name]: { ...existing, enabled: on, confirmed: existing?.confirmed ?? false },
    });
  }

  function confirmPending() {
    if (!pending) return;
    if (pending.kind === "mcp") {
      setField(pending.uid, { enabled: true, confirmed: true });
    } else {
      const existing = skills[pending.name];
      onSkillsChange({
        ...skills,
        [pending.name]: { ...existing, enabled: true, confirmed: true },
      });
    }
    setPending(null);
  }

  function submitNewSkill(event: React.FormEvent) {
    event.preventDefault();
    const name = newSkillName.trim();
    if (!skillNameValid(name) || createSkill.isPending) return;
    createSkill.mutate(name);
  }

  async function onImportFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Reset the input so picking the same file twice still fires change.
    event.target.value = "";
    if (!file) return;
    const content = await file.text();
    importSkill.mutate(content);
  }

  const trimmedNames = rows.map((row) => row.name.trim());
  const newNameInvalid = newSkillName.trim() !== "" && !skillNameValid(newSkillName.trim());
  // Rows the server reports as config-only ("missing" on disk) disappear
  // from the list once the user has removed them from the draft.
  const visibleSkills = (skillList.data ?? []).filter(
    (skill) => !(skill.errors.includes("missing") && !(skill.name in skills)),
  );

  return (
    <>
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
                    onChange={(event) => toggleServer(row, event.target.checked)}
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

      <Section title={t("settings.skills")} hint={t("settings.skills.hint")}
        action={
          <div className={styles.headActions}>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.markdown,text/markdown"
              hidden
              aria-hidden="true"
              onChange={onImportFile}
            />
            <button
              type="button"
              className={styles.headPrimary}
              onClick={() => setCreating(true)}
            >
              {t("settings.skills.add")}
            </button>
            <button
              type="button"
              className={styles.secondary}
              disabled={importSkill.isPending}
              onClick={() => fileInputRef.current?.click()}
            >
              {t("settings.skills.import")}
            </button>
          </div>
        }
      >
        {creating && (
          <form className={styles.skillCreate} onSubmit={submitNewSkill}>
            <label className={styles.field}>
              <span className={styles.label}>{t("settings.skills.name")}</span>
              <input
                className={styles.input}
                autoFocus
                aria-label={t("settings.skills.name")}
                placeholder="style-guide"
                value={newSkillName}
                onChange={(event) => {
                  setNewSkillName(event.target.value);
                  createSkill.reset();
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setCreating(false);
                    setNewSkillName("");
                    createSkill.reset();
                  }
                }}
              />
              {newNameInvalid && (
                <span className={styles.error}>{t("settings.skills.nameInvalid")}</span>
              )}
              {createSkill.isError && (
                <span className={styles.error}>{describeCreateError(createSkill.error)}</span>
              )}
            </label>
            <div className={styles.skillCreateActions}>
              <button
                type="submit"
                className={styles.headPrimary}
                disabled={!skillNameValid(newSkillName.trim()) || createSkill.isPending}
              >
                {t("settings.skills.addConfirm")}
              </button>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => {
                  setCreating(false);
                  setNewSkillName("");
                  createSkill.reset();
                }}
              >
                {t("settings.confirm.cancel")}
              </button>
            </div>
          </form>
        )}
        {importSkill.isError && (
          <p className={styles.skillFormError}>{describeImportError(importSkill.error)}</p>
        )}
        {skillList.data && visibleSkills.length === 0 && !creating && (
          <p className={styles.emptyBox}>{t("settings.skills.empty")}</p>
        )}
        {visibleSkills.map((skill) => {
          const skillConfig = skills[skill.name];
          const enabled = skillConfig?.enabled ?? false;
          // Enabled but unconfirmed (the core reset the flag after a
          // content change): the skill is not reaching the agent, say so
          // and offer the confirmation card again.
          const needsReconfirm =
            enabled && !(skillConfig?.confirmed ?? false) && skill.valid;
          return (
            <div key={skill.name} className={styles.skillRow}>
              <div className={styles.skillText}>
                <span className={styles.skillName}>{skill.name}</span>
                {skill.description && (
                  <p className={styles.skillDesc}>{skill.description}</p>
                )}
                {!skill.valid && (
                  <p className={styles.skillErrors}>
                    <span className={styles.errorPill}>
                      {t("settings.skills.invalid")}
                    </span>
                    {skill.errors.join("; ")}
                  </p>
                )}
                {needsReconfirm && (
                  <p className={styles.skillErrors}>
                    <span className={styles.errorPill}>
                      {t("settings.skills.unconfirmed")}
                    </span>
                    {t("settings.skills.unconfirmedHint")}
                  </p>
                )}
              </div>
              <div className={styles.skillActions}>
                <label className={styles.checkItem}>
                  <input
                    type="checkbox"
                    aria-label={`${t("settings.skills.enable")} ${skill.name}`}
                    checked={enabled}
                    disabled={!skill.valid && !enabled}
                    onChange={(event) => toggleSkill(skill.name, event.target.checked)}
                  />
                  {t("settings.skills.enable")}
                </label>
                {needsReconfirm && (
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={() => setPending({ kind: "skill", name: skill.name })}
                  >
                    {t("settings.skills.reconfirm")}
                  </button>
                )}
                {!skill.errors.includes("missing") && (
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={() => onEditSkill?.(skill.name)}
                  >
                    {t("settings.skills.edit")}
                  </button>
                )}
                <button
                  type="button"
                  className={styles.secondary}
                  disabled={deleteSkill.isPending}
                  onClick={() => deleteSkill.mutate(skill.name)}
                >
                  {t("settings.remove")}
                </button>
              </div>
            </div>
          );
        })}
      </Section>

      {pending && (
        <ConfirmCard
          pending={pending}
          tools={
            pending.kind === "mcp"
              ? (statusByName.get(pending.name)?.tools ?? [])
              : []
          }
          onConfirm={confirmPending}
          onCancel={() => setPending(null)}
        />
      )}
    </>
  );
}

function describeCreateError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return t("settings.skills.exists");
    if (error.status === 422 && Array.isArray(error.detail)) {
      return error.detail.join("; ");
    }
  }
  return t("settings.skills.createFailed");
}

function describeImportError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return t("settings.skills.exists");
    if (error.status === 422 && Array.isArray(error.detail)) {
      return `${t("settings.skills.importInvalid")}${error.detail.join("; ")}`;
    }
  }
  return t("settings.skills.importFailed");
}

function ConfirmCard({
  pending,
  tools,
  onConfirm,
  onCancel,
}: {
  pending: PendingConfirm;
  tools: McpToolInfo[];
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const api = useApi();
  const skillContent = useQuery({
    queryKey: ["skill", pending.kind === "skill" ? pending.name : ""],
    queryFn: () => api.getSkill(pending.name),
    enabled: pending.kind === "skill",
  });
  // The gate must not be passable before the content could have been
  // reviewed: while the skill body is loading or failed to load, the
  // accept button stays off.
  const acceptDisabled =
    pending.kind === "skill" && skillContent.data === undefined;
  const title =
    pending.kind === "mcp"
      ? t("settings.confirm.mcpTitle")
      : t("settings.confirm.skillTitle");
  return (
    <div className={styles.scrim}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={styles.confirmCard}
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
        }}
      >
        <h3 className={styles.confirmTitle}>{title}</h3>
        <p className={styles.confirmName}>{pending.name}</p>
        {pending.kind === "mcp" ? (
          <McpConfirmBody tools={tools} />
        ) : (
          <SkillConfirmBody
            content={skillContent.data?.content}
            isError={skillContent.isError}
          />
        )}
        <div className={styles.confirmActions}>
          <button
            type="button"
            autoFocus
            className={styles.secondaryButton}
            onClick={onCancel}
          >
            {t("settings.confirm.cancel")}
          </button>
          <button
            type="button"
            className={styles.primaryButton}
            disabled={acceptDisabled}
            onClick={onConfirm}
          >
            {t("settings.confirm.accept")}
          </button>
        </div>
      </div>
    </div>
  );
}

function McpConfirmBody({ tools }: { tools: McpToolInfo[] }) {
  if (tools.length === 0) {
    return <p className={styles.confirmIntro}>{t("settings.confirm.mcpNoTools")}</p>;
  }
  return (
    <>
      <p className={styles.confirmIntro}>{t("settings.confirm.mcpIntro")}</p>
      <ul className={styles.confirmTools}>
        {tools.map((tool) => (
          <li key={tool.name} className={styles.confirmTool}>
            <span className={styles.skillName}>{tool.name}</span>
            {tool.description && (
              <span className={styles.confirmToolDesc}>{tool.description}</span>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

function SkillConfirmBody({
  content,
  isError,
}: {
  content: string | undefined;
  isError: boolean;
}) {
  return (
    <>
      <p className={styles.confirmIntro}>{t("settings.confirm.skillIntro")}</p>
      {isError ? (
        <p className={styles.skillFormError}>{t("settings.confirm.loadFailed")}</p>
      ) : content !== undefined ? (
        <pre className={styles.confirmContent}>{content}</pre>
      ) : (
        <p className={styles.confirmIntro}>{t("editor.loading")}</p>
      )}
    </>
  );
}
