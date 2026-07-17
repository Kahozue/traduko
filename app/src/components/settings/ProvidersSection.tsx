import { useRef, useState } from "react";
import { t } from "../../i18n";
import type { ProviderConfigDoc } from "../../lib/api/types";
import { Section } from "./Section";
import styles from "./settings.module.css";

interface Row {
  uid: number;
  name: string;
  config: ProviderConfigDoc;
}

const OPTIONAL_FIELDS = ["api_key", "api_key_env", "model"] as const;

function needsBaseUrl(config: ProviderConfigDoc): boolean {
  return String(config.type ?? "openai_compat") === "openai_compat";
}

function normalize(rows: Row[]): Record<string, ProviderConfigDoc> | null {
  const out: Record<string, ProviderConfigDoc> = {};
  for (const row of rows) {
    const name = row.name.trim();
    if (!name || name in out) return null;
    if (needsBaseUrl(row.config) && String(row.config.base_url ?? "").trim() === "") {
      return null;
    }
    out[name] = row.config;
  }
  return out;
}

export function ProvidersSection({
  providers,
  onChange,
}: {
  providers: Record<string, ProviderConfigDoc>;
  onChange: (providers: Record<string, ProviderConfigDoc> | null) => void;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    Object.entries(providers).map(([name, config], index) => ({
      uid: index,
      name,
      config,
    })),
  );
  const nextUid = useRef(rows.length);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());

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
    if (value === "" && (OPTIONAL_FIELDS as readonly string[]).includes(key)) {
      delete config[key];
    }
    setRow(uid, { config });
  }

  function add() {
    const uid = nextUid.current;
    nextUid.current += 1;
    apply([...rows, { uid, name: "", config: { type: "openai_compat", base_url: "" } }]);
  }

  function toggleReveal(uid: number) {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }

  const trimmedNames = rows.map((row) => row.name.trim());

  return (
    <Section
      title={t("settings.providers")}
      action={
        <button
          type="button"
          className={`${styles.secondary} ${styles.headAction}`}
          onClick={add}
        >
          {t("settings.addProvider")}
        </button>
      }
    >
      {rows.length === 0 && <p className={styles.emptyBox}>{t("settings.providersEmpty")}</p>}
      {rows.map((row) => {
        const name = row.name.trim();
        const nameInvalid =
          !name || trimmedNames.filter((candidate) => candidate === name).length > 1;
        const baseUrl = String(row.config.base_url ?? "");
        const showBaseUrl = needsBaseUrl(row.config);
        return (
          <div key={row.uid} className={styles.card}>
            <div className={styles.cardHeader}>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.providerName")}</span>
                <input
                  className={styles.input}
                  aria-label={t("settings.providerName")}
                  value={row.name}
                  onChange={(event) => setRow(row.uid, { name: event.target.value })}
                />
                {nameInvalid && (
                  <span className={styles.error}>{t("settings.providerNameInvalid")}</span>
                )}
              </label>
              <span className={styles.typeTag}>
                {String(row.config.type ?? "openai_compat")}
              </span>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => apply(rows.filter((item) => item.uid !== row.uid))}
              >
                {t("settings.remove")}
              </button>
            </div>
            {showBaseUrl && (
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.baseUrl")}</span>
                <input
                  className={styles.input}
                  aria-label={t("settings.baseUrl")}
                  value={baseUrl}
                  onChange={(event) => setField(row.uid, "base_url", event.target.value)}
                />
                {baseUrl.trim() === "" && (
                  <span className={styles.error}>{t("settings.baseUrlRequired")}</span>
                )}
              </label>
            )}
            {showBaseUrl && (
              <div className={styles.fieldRow}>
                <label className={styles.field}>
                  <span className={styles.label}>{t("settings.apiKey")}</span>
                  <span className={styles.inline}>
                    <input
                      className={styles.input}
                      type={revealed.has(row.uid) ? "text" : "password"}
                      value={String(row.config.api_key ?? "")}
                      onChange={(event) => setField(row.uid, "api_key", event.target.value)}
                    />
                    <button
                      type="button"
                      className={styles.secondary}
                      onClick={() => toggleReveal(row.uid)}
                    >
                      {revealed.has(row.uid) ? t("settings.hide") : t("settings.reveal")}
                    </button>
                  </span>
                </label>
                <label className={styles.field}>
                  <span className={styles.label}>{t("settings.apiKeyEnv")}</span>
                  <input
                    className={styles.input}
                    value={String(row.config.api_key_env ?? "")}
                    onChange={(event) =>
                      setField(row.uid, "api_key_env", event.target.value)
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span className={styles.label}>{t("settings.defaultModel")}</span>
                  <input
                    className={styles.input}
                    value={String(row.config.model ?? "")}
                    onChange={(event) => setField(row.uid, "model", event.target.value)}
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
