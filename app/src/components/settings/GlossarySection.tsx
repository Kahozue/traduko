import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "../ConfirmDialog";
import { t } from "../../i18n";
import { ApiError } from "../../lib/api/client";
import type { GlossaryDomain, GlossaryTable } from "../../lib/api/types";
import { useApi } from "../../lib/connection";
import { humanizeError } from "../../lib/errors";
import { Section } from "./Section";
import styles from "./settings.module.css";

// Glossary tables are file-backed (glossaries/*.csv + manifest.json), so the
// section manages them directly via the API like the Skills list instead of
// going through the settings draft/save bar. One section per settings tab,
// each bound to its pipeline domain.
export function GlossarySection({
  domain,
  onEditGlossary,
}: {
  domain: GlossaryDomain;
  onEditGlossary?: (id: string) => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  // Deleting a table throws away every term in it, so it asks first.
  const [deleting, setDeleting] = useState<GlossaryTable | null>(null);

  const list = useQuery({
    queryKey: ["glossaries", domain],
    queryFn: () => api.listGlossaries(domain),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["glossaries"] });
  }

  // A rejected mutation used to leave the screen unchanged, so a bad import
  // read as "nothing happened". Every mutation now reports its reason here.
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);

  function failWith(prefix: string) {
    return (cause: unknown) => {
      const raw =
        cause instanceof ApiError && typeof cause.detail === "string"
          ? cause.detail
          : String(cause);
      setError(`${prefix}：${humanizeError(raw).summary}`);
    };
  }

  const create = useMutation({
    mutationFn: (name: string) => api.createGlossary(name, domain),
    onSuccess: () => {
      setCreating(false);
      setNewName("");
      setError(null);
      refresh();
    },
    onError: failWith(t("settings.glossary.actionFailed")),
  });

  const importTable = useMutation({
    mutationFn: ({
      name,
      content,
      format,
    }: {
      name: string;
      content: string;
      format: "csv" | "json";
    }) => api.importGlossary(name, domain, content, format),
    onSuccess: (table) => {
      setError(null);
      // The core reports every row it dropped; surfacing the count plus the
      // lines is the difference between a lost term and a fixable one.
      setSkipped(table.skipped ?? []);
      refresh();
    },
    onError: failWith(t("settings.glossary.importFailed")),
  });

  const patch = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.patchGlossary(id, { enabled }),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: failWith(t("settings.glossary.actionFailed")),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteGlossary(id),
    onSuccess: () => {
      setError(null);
      setDeleting(null);
      refresh();
    },
    onError: failWith(t("settings.glossary.actionFailed")),
  });

  function submitNew(event: React.FormEvent) {
    event.preventDefault();
    const name = newName.trim();
    if (!name || create.isPending) return;
    create.mutate(name);
  }

  async function onImportFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Reset the input so picking the same file twice still fires change.
    event.target.value = "";
    if (!file) return;
    setSkipped([]);
    const content = await file.text();
    const format = file.name.toLowerCase().endsWith(".json") ? "json" : "csv";
    const name = file.name.replace(/\.[^.]+$/, "");
    importTable.mutate({ name, content, format });
  }

  async function onExport(id: string, name: string, format: "csv" | "json") {
    const content = await api.exportGlossary(id, format);
    const type = format === "json" ? "application/json" : "text/csv";
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${name}.${format}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const tables = list.data ?? [];

  return (
    <Section
      title={t("settings.glossary")}
      action={
        <div className={styles.headActions}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.json,text/csv,application/json"
            hidden
            aria-hidden="true"
            aria-label={t("settings.glossary.importFile")}
            onChange={onImportFile}
          />
          <button
            type="button"
            className={styles.headPrimary}
            onClick={() => setCreating(true)}
          >
            {t("settings.glossary.add")}
          </button>
          <button
            type="button"
            className={styles.secondary}
            disabled={importTable.isPending}
            onClick={() => fileInputRef.current?.click()}
          >
            {t("settings.glossary.import")}
          </button>
        </div>
      }
    >
      {error && (
        <p className={styles.glossaryError} role="alert">
          {error}
        </p>
      )}
      {skipped.length > 0 && (
        <div className={styles.glossaryNotice} role="status">
          {t("settings.glossary.skippedPrefix")}
          {skipped.length}
          {t("settings.glossary.skippedSuffix")}
          <ul className={styles.glossarySkippedList}>
            {skipped.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {creating && (
        <form className={styles.skillCreate} onSubmit={submitNew}>
          <label className={styles.field}>
            <span className={styles.label}>{t("settings.glossary.name")}</span>
            <input
              className={styles.input}
              autoFocus
              aria-label={t("settings.glossary.name")}
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setCreating(false);
                  setNewName("");
                }
              }}
            />
          </label>
          <div className={styles.skillCreateActions}>
            <button
              type="submit"
              className={styles.headPrimary}
              disabled={!newName.trim() || create.isPending}
            >
              {t("settings.glossary.addConfirm")}
            </button>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => {
                setCreating(false);
                setNewName("");
              }}
            >
              {t("settings.confirm.cancel")}
            </button>
          </div>
        </form>
      )}
      {list.data && tables.length === 0 && !creating && (
        <p className={styles.emptyBox}>{t("settings.glossary.empty")}</p>
      )}
      {tables.map((table) => (
        <div key={table.id} className={styles.skillRow}>
          <div className={styles.skillText}>
            <button
              type="button"
              className={styles.glossaryName}
              onClick={() => onEditGlossary?.(table.id)}
            >
              {table.name}
            </button>
            <p className={styles.skillDesc}>
              {table.entry_count} {t("settings.glossary.entriesUnit")}
            </p>
          </div>
          <div className={styles.skillActions}>
            <label className={styles.checkItem}>
              <input
                type="checkbox"
                aria-label={`${t("settings.glossary.enable")} ${table.name}`}
                checked={table.enabled}
                onChange={(event) =>
                  patch.mutate({ id: table.id, enabled: event.target.checked })
                }
              />
              {t("settings.glossary.enable")}
            </label>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => void onExport(table.id, table.name, "csv")}
            >
              {t("settings.glossary.exportCsv")}
            </button>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => void onExport(table.id, table.name, "json")}
            >
              {t("settings.glossary.exportJson")}
            </button>
            <button
              type="button"
              className={styles.secondary}
              disabled={remove.isPending}
              onClick={() => setDeleting(table)}
            >
              {t("settings.remove")}
            </button>
          </div>
        </div>
      ))}
      {deleting && (
        <ConfirmDialog
          title={t("settings.glossary.deleteConfirm.title")}
          body={deleting.name}
          confirmLabel={t("settings.glossary.deleteConfirm.confirm")}
          cancelLabel={t("settings.confirm.cancel")}
          danger
          busy={remove.isPending}
          onConfirm={() => remove.mutate(deleting.id)}
          onCancel={() => setDeleting(null)}
        />
      )}
    </Section>
  );
}
