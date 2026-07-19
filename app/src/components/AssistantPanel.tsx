import { useEffect, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t, type MessageKey } from "../i18n";
import { ApiError } from "../lib/api/client";
import { humanizeError } from "../lib/errors";
import { localeStore } from "../lib/locale";
import { renderMarkdown } from "../lib/markdown";
import { formatDateTime } from "../lib/time";
import { assistantContextInfo } from "../lib/context";
import { assistantLive, useAssistantLive } from "../lib/events/store";
import type { IconName } from "./icons";
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

// Live tool-activity badge: icon and label per tool category.
const TOOL_ICONS: Record<string, IconName> = {
  read: "book-open",
  write: "pencil",
  execute: "cpu",
};

const TOOL_LABEL_KEYS: Record<string, MessageKey> = {
  read: "assistant.activity.read",
  write: "assistant.activity.write",
  execute: "assistant.activity.execute",
};

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
  const live = useAssistantLive();
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.getConfig(),
  });
  const contextInfo = useMemo(
    () => assistantContextInfo(config, messages),
    [config, messages],
  );
  // A proposal filed mid-run raises its card as soon as the event arrives,
  // not only after the whole turn returns.
  useEffect(() => {
    if (live.proposalVersion > 0) {
      void queryClient.invalidateQueries({ queryKey: PROPOSALS_KEY });
    }
  }, [live.proposalVersion, queryClient]);
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
  // Full-panel composer overlay for long messages.
  const [expanded, setExpanded] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // AbortController for the in-flight request, so "pause" can cancel it.
  const abortRef = useRef<AbortController | null>(null);

  const send = useMutation({
    mutationFn: (vars: { text: string; editIndex?: number; images?: string[] }) => {
      const controller = new AbortController();
      abortRef.current = controller;
      const promise = api.sendAssistantMessage(vars.text, {
        editIndex: vars.editIndex,
        images: vars.images,
        lang: localeStore.getLocale(),
      });
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
    // The sent message appears in the flow immediately (and the composer is
    // already cleared by submit); the server's reply replaces this snapshot.
    onMutate: (vars) => {
      const previous =
        queryClient.getQueryData<AssistantMessageDoc[]>(HISTORY_KEY) ?? [];
      const base =
        vars.editIndex !== undefined ? previous.slice(0, vars.editIndex) : previous;
      const optimistic: AssistantMessageDoc = {
        role: "user",
        text: vars.text,
        ts: new Date().toISOString(),
        ...(vars.images && vars.images.length > 0 ? { images: vars.images } : {}),
      };
      queryClient.setQueryData(HISTORY_KEY, [...base, optimistic]);
      return { previous };
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
    },
    onError: (_error, vars, context) => {
      // Roll the optimistic bubble back and hand the text back to the
      // composer for a retry — unless the user already typed something new.
      if (context) queryClient.setQueryData(HISTORY_KEY, context.previous);
      setDraft((current) => (current === "" ? vars.text : current));
      if (vars.images && vars.images.length > 0) {
        setAttachments((current) => (current.length === 0 ? vars.images ?? [] : current));
      }
      if (vars.editIndex !== undefined) setEditingIndex(vars.editIndex);
    },
    onSettled: () => {
      abortRef.current = null;
      // The turn is over (or abandoned): the live feed's job is done and the
      // persisted history now carries the messages.
      assistantLive.reset();
    },
  });

  const newChat = useMutation({
    // A fresh session keeps the old conversation in history; the previous
    // behavior (clearing the active session in place) destroyed it.
    mutationFn: () => api.createAssistantSession(),
    onSuccess: () => {
      queryClient.setQueryData(HISTORY_KEY, []);
      void queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
    },
  });

  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length, live.texts.length, live.streaming, live.tool]);

  // Grow the inline composer with its content (up to the CSS max-height) so
  // multi-line drafts stay readable without reaching for the expand overlay.
  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 132)}px`;
  }, [draft]);

  function submit() {
    const text = draft.trim();
    if (!text || send.isPending) return;
    setAttachError(false);
    send.reset();
    const vars = {
      text,
      editIndex: editingIndex ?? undefined,
      images: attachments.length > 0 ? attachments : undefined,
    };
    // Clear the composer right away: the message now lives in the flow as an
    // optimistic bubble, not in the input.
    setDraft("");
    setAttachments([]);
    setEditingIndex(null);
    setExpanded(false);
    send.mutate(vars);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  // In the expanded overlay Enter inserts a newline; Cmd/Ctrl+Enter sends.
  function onExpandedKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
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
        {contextInfo && <ContextGauge info={contextInfo} />}
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
          // Already on an empty conversation: nothing to preserve, so don't
          // pile up blank sessions in history.
          onClick={() => {
            if (messages.length > 0) newChat.mutate();
          }}
          disabled={newChat.isPending || send.isPending || messages.length === 0}
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
        {send.isPending && (live.texts.length > 0 || live.streaming || live.tool) && (
          <div className={styles.liveTurn}>
            {live.texts.map((text, index) => (
              <div key={`live-${index}`} className={styles.bubbleRow}>
                <div className={`${styles.bubble} ${styles.bubbleAssistant}`}>
                  <div className={styles.markdown}>{renderMarkdown(text)}</div>
                </div>
              </div>
            ))}
            {live.streaming && (
              <div className={styles.bubbleRow}>
                <div className={`${styles.bubble} ${styles.bubbleAssistant}`}>
                  <div className={styles.markdown}>
                    {renderMarkdown(live.streaming)}
                    <span className={styles.streamCursor} aria-hidden="true" />
                  </div>
                </div>
              </div>
            )}
            {live.tool && (
              <div className={styles.toolRow}>
                <span className={styles.toolBadge} data-kind={live.tool.kind} aria-hidden="true">
                  <Icon name={TOOL_ICONS[live.tool.kind] ?? "cpu"} size={13} />
                </span>
                <span>{t(TOOL_LABEL_KEYS[live.tool.kind] ?? "assistant.activity.execute")}</span>
                <span className={styles.toolName}>{live.tool.name}</span>
              </div>
            )}
          </div>
        )}
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
        <div className={styles.composer}>
          <textarea
            ref={textareaRef}
            className={styles.textarea}
            rows={1}
            value={draft}
            placeholder={t("assistant.inputPlaceholder")}
            disabled={send.isPending}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
          />
          <div className={styles.composerActions}>
            <button
              type="button"
              className={styles.composerButton}
              title={t("assistant.attach")}
              aria-label={t("assistant.attach")}
              disabled={send.isPending}
              onClick={pickImages}
            >
              <Icon name="paperclip" size={15} />
            </button>
            <button
              type="button"
              className={styles.composerButton}
              title={t("assistant.expand")}
              aria-label={t("assistant.expand")}
              disabled={send.isPending}
              onClick={() => setExpanded(true)}
            >
              <Icon name="expand" size={15} />
            </button>
            <button
              type="submit"
              className={styles.sendButton}
              disabled={send.isPending || draft.trim() === ""}
            >
              {t("assistant.send")}
            </button>
          </div>
        </div>
      </form>
      {expanded && (
        <div className={styles.expandOverlay}>
          <div className={styles.expandHead}>
            <span className={styles.expandTitle}>{t("assistant.expand.title")}</span>
            <button
              type="button"
              className={styles.headerButton}
              onClick={() => setExpanded(false)}
            >
              {t("assistant.expand.close")}
            </button>
          </div>
          <textarea
            className={styles.expandTextarea}
            value={draft}
            placeholder={t("assistant.inputPlaceholder")}
            disabled={send.isPending}
            autoFocus
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onExpandedKeyDown}
            onPaste={onPaste}
          />
          <div className={styles.expandFoot}>
            <span className={styles.expandHint}>{t("assistant.expand.hint")}</span>
            <button
              type="button"
              className={styles.sendButton}
              disabled={send.isPending || draft.trim() === ""}
              onClick={submit}
            >
              {t("assistant.send")}
            </button>
          </div>
        </div>
      )}
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
  const [query, setQuery] = useState("");
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
  const needle = query.trim().toLowerCase();
  const filtered =
    needle === ""
      ? rows
      : rows.filter((row) => row.title.toLowerCase().includes(needle));
  const hasSelection = selected.size > 0;

  return (
    <div className={styles.historyDrawer}>
      <div className={styles.historyHead}>
        <span className={styles.historyTitle}>{t("assistant.history")}</span>
        <button type="button" className={styles.historyClose} onClick={onClose}>
          {t("assistant.close")}
        </button>
      </div>
      <div className={styles.historySearch}>
        <Icon name="search" size={14} />
        <input
          className={styles.historySearchInput}
          value={query}
          placeholder={t("assistant.history.search")}
          aria-label={t("assistant.history.search")}
          onChange={(event) => setQuery(event.target.value)}
        />
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
        {rows.length > 0 && filtered.length === 0 && (
          <p className={styles.empty}>{t("assistant.history.noMatch")}</p>
        )}
        {filtered.map((row) => (
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
      <button type="button" className={styles.historyOpen} onClick={onOpen}>
        <span className={styles.historyRowTitle}>{row.title}</span>
        <span className={styles.historyRowMeta}>
          {formatDateTime(row.updated_at)} · {row.message_count}
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
          title={formatDateTime(message.ts)}
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

// 18px ring showing estimated context fill for the assistant's provider.
// Estimate only (CJK-weighted char count), so the label says so.
function ContextGauge({ info }: { info: { used: number; window: number; ratio: number } }) {
  const radius = 7;
  const circumference = 2 * Math.PI * radius;
  const warn = info.ratio > 0.85;
  const label = `${t("assistant.context.label")}: ${info.used.toLocaleString()} / ${info.window.toLocaleString()} tokens`;
  return (
    <span className={styles.contextGauge} role="img" aria-label={label} title={label}>
      <svg width="18" height="18" viewBox="0 0 18 18">
        <circle
          cx="9"
          cy="9"
          r={radius}
          fill="none"
          className={styles.contextTrack}
          strokeWidth="2.5"
        />
        <circle
          cx="9"
          cy="9"
          r={radius}
          fill="none"
          className={warn ? styles.contextFillWarn : styles.contextFill}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray={`${circumference * info.ratio} ${circumference}`}
          transform="rotate(-90 9 9)"
        />
      </svg>
    </span>
  );
}
