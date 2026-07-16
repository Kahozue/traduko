import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../i18n";
import { useApi, useConnection } from "../lib/connection";
import type { CoreConfigDoc } from "../lib/api/types";
import { BasicsSection } from "../components/settings/BasicsSection";
import styles from "./SettingsView.module.css";

function clone(config: CoreConfigDoc): CoreConfigDoc {
  // Config documents come from the JSON API, so a JSON round trip is a
  // faithful deep copy.
  return JSON.parse(JSON.stringify(config)) as CoreConfigDoc;
}

export function SettingsView() {
  const api = useApi();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["config"], queryFn: () => api.getConfig() });

  const [draft, setDraft] = useState<CoreConfigDoc | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [numbersValid, setNumbersValid] = useState(true);
  const [providersValid, setProvidersValid] = useState(true);
  const [channelsValid, setChannelsValid] = useState(true);

  useEffect(() => {
    if (data && draft === null) setDraft(clone(data));
  }, [data, draft]);

  const dirty = useMemo(
    () =>
      draft !== null && data !== undefined && JSON.stringify(draft) !== JSON.stringify(data),
    [draft, data],
  );
  const projectValid = draft !== null && draft.default_project.trim() !== "";
  const valid = numbersValid && providersValid && channelsValid && projectValid;

  const save = useMutation({
    mutationFn: () => api.saveConfig(draft as CoreConfigDoc),
    onSuccess: (saved) => {
      queryClient.setQueryData(["config"], saved);
      setDraft(clone(saved));
      setResetKey((key) => key + 1);
      queryClient.invalidateQueries({ queryKey: ["budget"] });
    },
  });

  function discard() {
    if (data) setDraft(clone(data));
    setNumbersValid(true);
    setProvidersValid(true);
    setChannelsValid(true);
    setResetKey((key) => key + 1);
  }

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
