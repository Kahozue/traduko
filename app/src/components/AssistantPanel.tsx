import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t, type MessageKey } from "../i18n";
import { ApiError } from "../lib/api/client";
import type { AssistantMessageDoc, ProposalDoc } from "../lib/api/types";
import { useApi } from "../lib/connection";
import styles from "./AssistantPanel.module.css";

const HISTORY_KEY = ["assistant", "history"] as const;
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

  // Proposal cards render on the assistant messages that filed them
  // (message.proposal_ids). One shared query backs every card in the
  // panel; approve/reject mutations are shared too and keyed by the
  // proposal id currently in flight so each card can show its own
  // pending/error state independently.
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
          <MessageBubble
            key={`${message.role}-${message.ts}-${index}`}
            message={message}
            proposals={proposalsById}
            proposalsLoading={proposals.isLoading}
            onApprove={(id) => approveProposal.mutate(id)}
            onReject={(id) => rejectProposal.mutate(id)}
            approvingId={approveProposal.isPending ? approveProposal.variables : undefined}
            rejectingId={rejectProposal.isPending ? rejectProposal.variables : undefined}
            approveFailedId={approveProposal.isError ? approveProposal.variables : undefined}
            rejectFailedId={rejectProposal.isError ? rejectProposal.variables : undefined}
          />
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
}) {
  const isUser = message.role === "user";
  const proposalIds = message.proposal_ids ?? [];
  return (
    <div className={`${styles.bubbleRow} ${isUser ? styles.bubbleRowUser : ""}`}>
      <div className={styles.bubbleColumn}>
        <div className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAssistant}`}>
          {message.text}
        </div>
        {proposalIds.map((id) => {
          const proposal = proposals[id];
          if (!proposal) {
            // Loading: the shared proposals query hasn't resolved yet — say
            // nothing rather than flash a false "gone" note. Resolved but
            // absent: the id genuinely doesn't map to a known proposal, so
            // say so instead of silently dropping the card.
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
            <span
              // Diff lines carry no stable identity of their own; index is
              // fine because the list only ever renders once per proposal.
              key={index}
              className={styles.diffLine}
              data-kind={diffLineKind(line)}
            >
              {line.length > 0 ? line : " "}
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
