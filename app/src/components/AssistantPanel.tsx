import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../i18n";
import { ApiError } from "../lib/api/client";
import type { AssistantMessageDoc } from "../lib/api/types";
import { useApi } from "../lib/connection";
import styles from "./AssistantPanel.module.css";

const HISTORY_KEY = ["assistant", "history"] as const;

// Right-docked assistant panel: message flow + input row. The panel is
// mounted only while open (AppShell owns that toggle); history survives a
// close/reopen because it lives in the shared react-query cache, not local
// state. staleTime: Infinity keeps that cache authoritative — the only
// writes come from this component's own mutations (send returns the fresh
// history, clear resets it to []) — so remounting never races a background
// refetch against those writes.
export function AssistantPanel({ onClose }: { onClose: () => void }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const history = useQuery({
    queryKey: HISTORY_KEY,
    queryFn: () => api.getAssistantHistory(),
    staleTime: Infinity,
  });
  const messages = history.data ?? [];

  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const send = useMutation({
    mutationFn: (text: string) => api.sendAssistantMessage(text),
    onSuccess: (data) => {
      queryClient.setQueryData(HISTORY_KEY, data.history);
      setDraft("");
    },
  });

  const clear = useMutation({
    mutationFn: () => api.clearAssistant(),
    onSuccess: () => {
      queryClient.setQueryData(HISTORY_KEY, []);
    },
  });

  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length]);

  function submit() {
    const text = draft.trim();
    if (!text || send.isPending) return;
    send.reset();
    send.mutate(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  const providerMissing =
    send.isError && send.error instanceof ApiError && send.error.status === 409;

  return (
    <aside className={styles.panel}>
      <div className={styles.header}>
        <h2 className={styles.title}>{t("assistant.title")}</h2>
        <button
          type="button"
          className={styles.headerButton}
          disabled={clear.isPending}
          onClick={() => clear.mutate()}
        >
          {t("assistant.clear")}
        </button>
        <button type="button" className={styles.headerButton} onClick={onClose}>
          {t("assistant.close")}
        </button>
      </div>
      <div className={styles.messages} ref={listRef}>
        {history.isLoading && <p className={styles.empty}>{t("assistant.loading")}</p>}
        {!history.isLoading && messages.length === 0 && (
          <p className={styles.empty}>{t("assistant.empty")}</p>
        )}
        {messages.map((message, index) => (
          <MessageBubble key={`${message.role}-${message.ts}-${index}`} message={message} />
        ))}
      </div>
      {send.isError && (
        <p className={styles.notice}>
          {providerMissing ? t("assistant.providerUnavailable") : t("assistant.error")}
        </p>
      )}
      {send.isPending && (
        <div className={styles.busyRow}>
          <span className={styles.spinner} aria-hidden="true" />
          {t("assistant.busy")}
        </div>
      )}
      <form
        className={styles.footer}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <textarea
          className={styles.textarea}
          rows={1}
          value={draft}
          placeholder={t("assistant.inputPlaceholder")}
          disabled={send.isPending}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button
          type="submit"
          className={styles.sendButton}
          disabled={send.isPending || draft.trim() === ""}
        >
          {t("assistant.send")}
        </button>
      </form>
    </aside>
  );
}

function MessageBubble({ message }: { message: AssistantMessageDoc }) {
  const isUser = message.role === "user";
  return (
    <div className={`${styles.bubbleRow} ${isUser ? styles.bubbleRowUser : ""}`}>
      <div className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAssistant}`}>
        {message.text}
      </div>
      {/* Task 5 seam: for an assistant message with message.proposal_ids,
          a ProposalCard (diff, approve/reject) renders here once that
          lands. Nothing to build yet — the reply text already carries any
          non-convergence reason, and this loop already has the full
          AssistantMessageDoc to extend without restructuring. */}
    </div>
  );
}
