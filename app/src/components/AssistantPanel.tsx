import { useEffect, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t, type MessageKey } from "../i18n";
import { ApiError } from "../lib/api/client";
import { humanizeError } from "../lib/errors";
import { renderMarkdown } from "../lib/markdown";
import type {
  AssistantMessageDoc,
  AssistantSessionRow,
  ProposalDoc,
} from "../lib/api/types";
import { useApi } from "../lib/connection";
import { Icon } from "./icons";
import styles from "./AssistantPanel.module.css";

const HISTORY_KEY = ["assistant", "history"] as const;
const SESSIONS_KEY = ["assistant", "sessions"] as const;
const PROPOSALS_KEY = ["proposals"] as const;

const PROPOSAL_STATUS_KEYS: Record<ProposalDoc["status"], MessageKey> = {
  pending: "assistant.proposal.pending",
  applied: "assistant.proposal.applied",
  rejected: "assistant.proposal.rejected",
};

type DiffLineKind = "add" | "remove" | "meta" | "context";

function diffLineKind(line: string): DiffLineKind {
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) return "meta";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "remove";
  return "context";
}

function diffLines(diff: string): string[] {
  return diff.replace(/\n$/, "").split("\n");
}

// Full timestamp for the hover tooltip; the bubbles themselves stay clean.
function formatFullTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("zh-TW");
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

// The core stores a canned English reply when the agent loop does not
// converge; the reason code maps to zh-TW wording here so the stored
// history stays raw while the UI reads naturally.
const FAIL_REASON_KEYS: Record<string, MessageKey> = {
  protocol_error: "assistant.fail.protocol_error",
  max_rounds: "assistant.fail.max_rounds",
  max_turns: "assistant.fail.max_turns",
  budget: "assistant.fail.budget",
};

const NOT_CONVERGED_RE =
  /^I could not finish processing this message \(reason: ([a-z_]*)\)\./;

function localizeAssistantText(text: string): string {
  const match = NOT_CONVERGED_RE.exec(text);
  if (!match) return text;
  return t(FAIL_REASON_KEYS[match[1]] ?? "assistant.fail.generic");
}

// Right-docked assistant panel: message flow + input row, with a history
// drawer over conversation sessions. History survives close/reopen because it
// lives in the shared react-query cache (staleTime Infinity), authoritative
// against this component's own mutations.
export function AssistantPanel({ onClose }: { onClose: () => void }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const history = useQuery({
    queryKey: HISTORY_KEY,
    queryFn: () => api.getAssistantHistory(),
    staleTime: Infinity,
  });
  const messages = history.data ?? [];

  const proposals = useQuery({
    queryKey: PROPOSALS_KEY,
    queryFn: () => api.listProposals(),
  });
  const proposalsById = useMemo(() => {
    const map: Record<string, ProposalDoc> = {};
    for (const proposal of proposals.data ?? []) map[proposal.id] = proposal;
    return map;
  }, [proposals.data]);

  const approveProposal = useMutation({
    mutationFn: (id: string) => api.approveProposal(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROPOSALS_KEY });
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  const rejectProposal = useMutation({
    mutationFn: (id: string) => api.rejectProposal(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROPOSALS_KEY });
    },
  });

  const [draft, setDraft] = useState("");
  // Paths of images attached to the message being composed.
  const [attachments, setAttachments] = useState<string[]>([]);
  // True after a clipboard-image upload fails; cleared on the next paste/send.
  const [attachError, setAttachError] = useState(false);
  // Non-null while an earlier user message is being edited; carries its index
  // so send truncates the session there before rerunning.
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  // AbortController for the in-flight request, so "pause" can cancel it.
  const abortRef = useRef<AbortController | null>(null);

  const send = useMutation({
    mutationFn: (vars: { text: string; editIndex?: number; images?: string[] }) => {
      const controller = new AbortController();
      abortRef.current = controller;
      const opts =
        vars.editIndex !== undefined || (vars.images && vars.images.length > 0)
          ? { editIndex: vars.editIndex, images: vars.images }
          : undefined;
      const promise = opts
        ? api.sendAssistantMessage(vars.text, opts)
        : api.sendAssistantMessage(vars.text);
      // Reject the mutation if the user pauses before the reply lands.
      return new Promise<Awaited<ReturnType<typeof api.sendAssistantMessage>>>(
        (resolve, reject) => {
          controller.signal.addEventListener("abort", () =>
            reject(new DOMException("paused", "AbortError")),
          );
          promise.then(resolve, reject);
        },
      );
    },
    onSuccess: (data) => {
      queryClient.setQueryData(HISTORY_KEY, data.history);
      if (data.proposal_ids.length > 0) {
        void queryClient.invalidateQueries({ queryKey: PROPOSALS_KEY });
      }
      // A reply that created tasks changed the task list; refresh it so the
      // new pending task appears without a manual reload.
      if (data.created_task_ids && data.created_task_ids.length > 0) {
        void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      }
      void queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
      setDraft("");
      setAttachments([]);
      setEditingIndex(null);
    },
    onSettled: () => {
      abortRef.current = null;
    },
  });

  const clear = useMutation({
    mutationFn: () => api.clearAssistant(),
    onSuccess: () => {
      queryClient.setQueryData(HISTORY_KEY, []);
      void queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
    },
  });

  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length]);

  function submit() {
    const text = draft.trim();
    if (!text || send.isPending) return;
    setAttachError(false);
    send.reset();
    send.mutate({
      text,
      editIndex: editingIndex ?? undefined,
      images: attachments.length > 0 ? attachments : undefined,
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  function pause() {
    abortRef.current?.abort();
  }

  function startEdit(index: number, text: string) {
    setEditingIndex(index);
    setDraft(text);
  }

  function cancelEdit() {
    setEditingIndex(null);
    setDraft("");
  }

  async function pickImages() {
    // Native picker only exists inside the Tauri webview.
    if (!("__TAURI_INTERNALS__" in window)) return;
    const { open } = await import("@tauri-apps/plugin-dialog");
    const chosen = await open({
      multiple: true,
      filters: [{ name: "圖片", extensions: ["png", "jpg", "jpeg", "webp", "gif"] }],
    });
    if (!chosen) return;
    const paths = Array.isArray(chosen) ? chosen : [chosen];
    setAttachments((prev) => [...prev, ...paths]);
  }

  // Clipboard images have no file path, so they go through the core's
  // attachment endpoint, which saves the bytes and returns a path that rides
  // the same `images` channel as picker-chosen files. Text paste is untouched.
  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData?.items ?? [])
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (files.length === 0) return;
    event.preventDefault();
    setAttachError(false);
    void (async () => {
      try {
        for (const file of files) {
          const dataUrl = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result));
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(file);
          });
          const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
          const { path } = await api.uploadAssistantAttachment(file.type, base64);
          setAttachments((prev) => [...prev, path]);
        }
      } catch {
        setAttachError(true);
      }
    })();
  }

  const sendError = send.isError && !(send.error instanceof DOMException);
  const providerMissing =
    sendError && send.error instanceof ApiError && send.error.status === 409;
  const humanized =
    sendError && send.error instanceof ApiError && send.error.status === 502
      ? humanizeError(String(send.error.detail))
      : null;

  return (
    <aside className={styles.panel}>
      <div className={styles.header}>
        <h2 className={styles.title}>{t("assistant.title")}</h2>
        <button
          type="button"
          className={styles.iconButton}
          title={t("assistant.history")}
          aria-label={t("assistant.history")}
          aria-pressed={showHistory}
          onClick={() => setShowHistory((open) => !open)}
        >
          <Icon name="list" size={16} />
        </button>
        <button
          type="button"
          className={styles.iconButton}
          title={t("assistant.newChat")}
          aria-label={t("assistant.newChat")}
          onClick={() => clear.mutate()}
          disabled={clear.isPending}
        >
          <Icon name="pencil" size={16} />
        </button>
        <button type="button" className={styles.headerButton} onClick={onClose}>
          {t("assistant.close")}
        </button>
      </div>
      {showHistory && (
        <HistoryDrawer
          onClose={() => setShowHistory(false)}
          onSwitched={() => {
            setShowHistory(false);
            setEditingIndex(null);
            setDraft("");
          }}
        />
      )}
      <div className={styles.messages} ref={listRef}>
        {history.isLoading && <p className={styles.empty}>{t("assistant.loading")}</p>}
        {!history.isLoading && messages.length === 0 && (
          <p className={styles.empty}>{t("assistant.empty")}</p>
        )}
        {messages.map((message, index) => (
          <MessageBubble
            key={`${message.role}-${message.ts}-${index}`}
            message={message}
            proposals={proposalsById}
            proposalsLoading={proposals.isLoading || proposals.isError}
            onApprove={(id) => approveProposal.mutate(id)}
            onReject={(id) => rejectProposal.mutate(id)}
            approvingId={approveProposal.isPending ? approveProposal.variables : undefined}
            rejectingId={rejectProposal.isPending ? rejectProposal.variables : undefined}
            approveFailedId={approveProposal.isError ? approveProposal.variables : undefined}
            rejectFailedId={rejectProposal.isError ? rejectProposal.variables : undefined}
            onEdit={
              message.role === "user" && !send.isPending
                ? () => startEdit(index, message.text)
                : undefined
            }
          />
        ))}
      </div>
      {sendError && (
        <p className={styles.notice}>
          {providerMissing
            ? t("assistant.providerUnavailable")
            : humanized
              ? humanized.hint
                ? `${humanized.summary}——${humanized.hint}`
                : humanized.summary
              : t("assistant.error")}
        </p>
      )}
      {send.isPending && (
        <div className={styles.busyRow}>
          <span className={styles.spinner} aria-hidden="true" />
          {t("assistant.busy")}
          <button type="button" className={styles.pauseButton} onClick={pause}>
            {t("assistant.pause")}
          </button>
        </div>
      )}
      {editingIndex !== null && (
        <div className={styles.editBanner}>
          {t("assistant.editing")}
          <button type="button" className={styles.editCancel} onClick={cancelEdit}>
            {t("assistant.editCancel")}
          </button>
        </div>
      )}
      {attachments.length > 0 && (
        <div className={styles.attachRow}>
          {attachments.map((path, index) => (
            <span key={`${path}-${index}`} className={styles.attachChip} title={path}>
              {baseName(path)}
              <button
                type="button"
                className={styles.attachRemove}
                aria-label={t("assistant.attachRemove")}
                onClick={() => setAttachments((prev) => prev.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {attachError && (
        <p className={styles.attachError}>{t("assistant.attachFailed")}</p>
      )}
      <form
        className={styles.footer}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <button
          type="button"
          className={styles.attachButton}
          title={t("assistant.attach")}
          aria-label={t("assistant.attach")}
          disabled={send.isPending}
          onClick={pickImages}
        >
          <Icon name="cpu" size={16} />
        </button>
        <textarea
          className={styles.textarea}
          rows={1}
          value={draft}
          placeholder={t("assistant.inputPlaceholder")}
          disabled={send.isPending}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
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

function HistoryDrawer({
  onClose,
  onSwitched,
}: {
  onClose: () => void;
  onSwitched: () => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const sessions = useQuery({
    queryKey: SESSIONS_KEY,
    queryFn: () => api.listAssistantSessions(),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
    void queryClient.invalidateQueries({ queryKey: HISTORY_KEY });
  }

  const activate = useMutation({
    mutationFn: (id: string) => api.activateAssistantSession(id),
    onSuccess: () => {
      refresh();
      onSwitched();
    },
  });

  const bulkArchive = useMutation({
    mutationFn: (archived: boolean) =>
      Promise.allSettled(
        [...selected].map((id) => api.archiveAssistantSession(id, archived)),
      ),
    onSuccess: () => {
      setSelected(new Set());
      void queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
    },
  });

  const bulkDelete = useMutation({
    mutationFn: () =>
      Promise.allSettled([...selected].map((id) => api.deleteAssistantSession(id))),
    onSuccess: () => {
      setSelected(new Set());
      refresh();
    },
  });

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const rows = sessions.data ?? [];
  const hasSelection = selected.size > 0;

  return (
    <div className={styles.historyDrawer}>
      <div className={styles.historyHead}>
        <span className={styles.historyTitle}>{t("assistant.history")}</span>
        <button type="button" className={styles.historyClose} onClick={onClose}>
          {t("assistant.close")}
        </button>
      </div>
      {hasSelection && (
        <div className={styles.historyBulk}>
          <span>
            {t("assistant.selected")} {selected.size}
          </span>
          <button
            type="button"
            className={styles.historyBulkButton}
            onClick={() => bulkArchive.mutate(true)}
          >
            {t("assistant.archive")}
          </button>
          <button
            type="button"
            className={styles.historyBulkButton}
            onClick={() => bulkArchive.mutate(false)}
          >
            {t("assistant.unarchive")}
          </button>
          <button
            type="button"
            className={styles.historyBulkDanger}
            onClick={() => bulkDelete.mutate()}
          >
            {t("assistant.delete")}
          </button>
        </div>
      )}
      <div className={styles.historyList}>
        {rows.length === 0 && <p className={styles.empty}>{t("assistant.history.empty")}</p>}
        {rows.map((row) => (
          <HistoryRow
            key={row.id}
            row={row}
            selected={selected.has(row.id)}
            onToggle={() => toggle(row.id)}
            onOpen={() => activate.mutate(row.id)}
          />
        ))}
      </div>
    </div>
  );
}

function HistoryRow({
  row,
  selected,
  onToggle,
  onOpen,
}: {
  row: AssistantSessionRow;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  return (
    <div className={`${styles.historyRow} ${row.active ? styles.historyRowActive : ""}`}>
      <input
        type="checkbox"
        className={styles.historyCheck}
        aria-label={`${t("tasks.selectRow")} ${row.title}`}
        checked={selected}
        onChange={onToggle}
      />
      <button
        type="button"
        className={styles.historyOpen}
        title={formatFullTime(row.updated_at)}
        onClick={onOpen}
      >
        <span className={styles.historyRowTitle}>{row.title}</span>
        <span className={styles.historyRowMeta}>
          {row.message_count}
          {row.archived ? ` · ${t("assistant.archived")}` : ""}
        </span>
      </button>
    </div>
  );
}

function MessageBubble({
  message,
  proposals,
  proposalsLoading,
  onApprove,
  onReject,
  approvingId,
  rejectingId,
  approveFailedId,
  rejectFailedId,
  onEdit,
}: {
  message: AssistantMessageDoc;
  proposals: Record<string, ProposalDoc>;
  proposalsLoading: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  approvingId: string | undefined;
  rejectingId: string | undefined;
  approveFailedId: string | undefined;
  rejectFailedId: string | undefined;
  onEdit?: () => void;
}) {
  const isUser = message.role === "user";
  const proposalIds = message.proposal_ids ?? [];
  const images = message.images ?? [];
  return (
    <div className={`${styles.bubbleRow} ${isUser ? styles.bubbleRowUser : ""}`}>
      <div className={styles.bubbleColumn}>
        <div
          className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAssistant}`}
          title={formatFullTime(message.ts)}
        >
          {isUser ? (
            message.text
          ) : (
            <div className={styles.markdown}>
              {renderMarkdown(localizeAssistantText(message.text))}
            </div>
          )}
          {images.length > 0 && (
            <div className={styles.bubbleAttachments}>
              {images.map((path, index) => (
                <span key={`${path}-${index}`} className={styles.bubbleAttachment} title={path}>
                  {baseName(path)}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className={styles.bubbleMeta}>
          {!isUser && message.model && (
            <span className={styles.modelChip}>{message.model}</span>
          )}
          {isUser && onEdit && (
            <button type="button" className={styles.editButton} onClick={onEdit}>
              {t("assistant.edit")}
            </button>
          )}
        </div>
        {proposalIds.map((id) => {
          const proposal = proposals[id];
          if (!proposal) {
            return proposalsLoading ? null : (
              <p key={id} className={styles.proposalMissing}>
                {t("assistant.proposal.missing")}
              </p>
            );
          }
          return (
            <ProposalCard
              key={id}
              proposal={proposal}
              onApprove={() => onApprove(id)}
              onReject={() => onReject(id)}
              approving={approvingId === id}
              rejecting={rejectingId === id}
              approveFailed={approveFailedId === id}
              rejectFailed={rejectFailedId === id}
            />
          );
        })}
      </div>
    </div>
  );
}

function ProposalCard({
  proposal,
  onApprove,
  onReject,
  approving,
  rejecting,
  approveFailed,
  rejectFailed,
}: {
  proposal: ProposalDoc;
  onApprove: () => void;
  onReject: () => void;
  approving: boolean;
  rejecting: boolean;
  approveFailed: boolean;
  rejectFailed: boolean;
}) {
  const busy = approving || rejecting;
  return (
    <div className={styles.proposalCard}>
      <div className={styles.proposalHeader}>
        <span className={styles.proposalTitle}>{t("assistant.proposal.title")}</span>
        <span className={styles.proposalStatus} data-status={proposal.status}>
          {t(PROPOSAL_STATUS_KEYS[proposal.status])}
        </span>
      </div>
      {proposal.reason && <p className={styles.proposalReason}>{proposal.reason}</p>}
      {proposal.diff.trim() !== "" && (
        <pre className={styles.diff}>
          {diffLines(proposal.diff).map((line, index) => (
            <span key={index} className={styles.diffLine} data-kind={diffLineKind(line)}>
              {line.length > 0 ? line : " "}
            </span>
          ))}
        </pre>
      )}
      {proposal.status === "pending" && (
        <div className={styles.proposalActions}>
          <button
            type="button"
            className={styles.proposalReject}
            disabled={busy}
            onClick={onReject}
          >
            {rejecting ? t("assistant.proposal.rejecting") : t("assistant.proposal.reject")}
          </button>
          <button
            type="button"
            className={styles.proposalApprove}
            disabled={busy}
            onClick={onApprove}
          >
            {approving ? t("assistant.proposal.approving") : t("assistant.proposal.approve")}
          </button>
        </div>
      )}
      {approveFailed && (
        <p className={styles.proposalError}>{t("assistant.proposal.approveFailed")}</p>
      )}
      {rejectFailed && (
        <p className={styles.proposalError}>{t("assistant.proposal.rejectFailed")}</p>
      )}
    </div>
  );
}
