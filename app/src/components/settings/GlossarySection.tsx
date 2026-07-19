import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../../i18n";
import type { GlossaryDomain } from "../../lib/api/types";
import { useApi } from "../../lib/connection";
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

  const list = useQuery({
    queryKey: ["glossaries", domain],
    queryFn: () => api.listGlossaries(domain),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["glossaries"] });
  }

  const create = useMutation({
    mutationFn: (name: string) => api.createGlossary(name, domain),
    onSuccess: () => {
      setCreating(false);
      setNewName("");
      refresh();
    },
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
    onSuccess: refresh,
  });

  const patch = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.patchGlossary(id, { enabled }),
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteGlossary(id),
    onSuccess: refresh,
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
    const content = await file.text();
    const format = file.name.toLowerCase().endsWith(".json") ? "json" : "csv";
    const name = file.name.replace(/\.[^.]+$/, "");
    importTable.mutate({ name, content, format });
  }

  async function onExport(id: string, name: string) {
    const content = await api.exportGlossary(id, "csv");
    const url = URL.createObjectURL(new Blob([content], { type: "text/csv" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${name}.csv`;
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
              onClick={() => void onExport(table.id, table.id)}
            >
              {t("settings.glossary.export")}
            </button>
            <button
              type="button"
              className={styles.secondary}
              disabled={remove.isPending}
              onClick={() => remove.mutate(table.id)}
            >
              {t("settings.remove")}
            </button>
          </div>
        </div>
      ))}
    </Section>
  );
}
