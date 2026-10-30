"use client";

import React, { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { api } from "@/lib/client";
import {
  approvalOutcome,
  buildCases,
  MISMATCH_DECISION_LABEL,
  mismatchOutcome,
  type ApprovalCase,
  type DecisionCase,
  type MismatchCase,
} from "@/lib/views/decisions";
import { useLive, useSession } from "@/components/session";
import { dataOf, useNow, type PollState } from "@/components/usePoll";
import { Button, cx, EmptyState, ErrorState, ForbiddenState, Freshness, LoadingState, PageHeader, Pill } from "@/components/ui";

const SEV_TONE = { High: "warn", Medium: "neutral", Low: "neutral" } as const;

function sourceProblem(label: string, s: PollState<unknown>, onRetry: () => void): React.ReactNode {
  if (s.status !== "error") return null;
  if (s.error.kind === "not_found") {
    return (
      <ErrorState
        error={new ApiError("not_found", 404, s.error.code, `${label}: this field-api does not offer the list yet. Update the backend, then try again.`, null)}
        onRetry={onRetry}
      />
    );
  }
  if (s.error.kind === "forbidden") return <ForbiddenState role="Supervisor" />;
  return <ErrorState error={new ApiError(s.error.kind, s.error.status, s.error.code, `${label}: ${s.error.title}`, null)} onRetry={onRetry} />;
}

function CaseButton({ c, on, onPick }: { c: DecisionCase; on: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={on}
      className={cx(
        "flex flex-col gap-0.5 rounded-card border-2 px-3.5 py-3 text-left",
        on ? "border-primary bg-selected-soft" : "border-line bg-card hover:border-control",
      )}
    >
      <span className="flex justify-between gap-2">
        <b>{c.title}</b>
        <Pill tone={SEV_TONE[c.severity]}>{c.severity}</Pill>
      </span>
      <span className="text-sm text-muted">
        {c.kind} · {c.sub}
      </span>
      <span className="text-[13px] text-muted">{c.waiting}</span>
    </button>
  );
}

function Detail({ c, onDone }: { c: DecisionCase; onDone: (message: string) => void }) {
  const { can } = useSession();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reasonMissing, setReasonMissing] = useState(false);
  useEffect(() => {
    setReason("");
    setError(null);
    setReasonMissing(false);
  }, [c.key]);

  const blockedBySod = c.sod.mayDecide === false;

  async function act(run: () => Promise<string>) {
    if (!reason.trim()) {
      setReasonMissing(true);
      return;
    }
    setReasonMissing(false);
    setBusy(true);
    setError(null);
    try {
      onDone(await run());
    } catch (e) {
      setError(e instanceof ApiError ? e.title : "The decision was not saved.");
    } finally {
      setBusy(false);
    }
  }

  let buttons: React.ReactNode;
  let permissionNote: string | null = null;
  if (c.source === "approval") {
    const ac = c as ApprovalCase;
    const canApprove = can("field.discrepancy.approve");
    const canRecount = can("field.recount.assign");
    if (!canApprove) permissionNote = "Approving or rejecting needs the Supervisor or Inventory controller role.";
    const approve = (
      <Button
        key="approve"
        variant={ac.suggestion.action === "approve" ? "primary" : "secondary"}
        disabled={busy || blockedBySod || !canApprove}
        onClick={() => act(async () => approvalOutcome("approve", await api.decideApproval(ac.id, "approve", reason.trim())))}
      >
        Approve the difference
      </Button>
    );
    const recount = (
      <Button
        key="recount"
        variant={ac.suggestion.action === "recount" ? "primary" : "secondary"}
        disabled={busy || !canRecount || !ac.taskId}
        onClick={() =>
          act(async () => {
            await api.requestRecount(ac.taskId as string, reason.trim());
            return approvalOutcome("recount", null);
          })
        }
      >
        Ask for a recount
      </Button>
    );
    const reject = (
      <Button
        key="reject"
        variant="secondary"
        disabled={busy || blockedBySod || !canApprove}
        onClick={() => act(async () => approvalOutcome("reject", await api.decideApproval(ac.id, "reject", reason.trim())))}
      >
        Reject the difference
      </Button>
    );
    buttons = ac.suggestion.action === "approve" ? [approve, recount, reject] : [recount, approve, reject];
    if (!ac.taskId) permissionNote = [permissionNote, "A recount needs the count job, and field-api did not send it for this case."].filter(Boolean).join(" ");
  } else {
    const mc = c as MismatchCase;
    const canDecide = can("field.exception.decide");
    if (!canDecide) permissionNote = "Deciding tower findings needs the Supervisor role.";
    buttons = mc.decisions.map((d, i) => (
      <Button
        key={d}
        variant={i === 0 ? "primary" : "secondary"}
        disabled={busy || blockedBySod || !canDecide}
        onClick={() => act(async () => mismatchOutcome(d, await api.decideMismatch(mc.id, d, reason.trim(), mc.capturedBy)))}
      >
        {MISMATCH_DECISION_LABEL[d] ?? d}
      </Button>
    ));
  }

  return (
    <div className="flex min-w-0 flex-[999_1_420px] flex-col gap-3.5 rounded-card border border-line bg-card p-5">
      <div>
        <div className="text-[13px] text-muted">{c.kind}</div>
        <h2 className="m-0 text-2xl font-bold">{c.title}</h2>
        <div className="text-sm text-muted">{c.sub}</div>
      </div>
      {c.facts.length ? (
        <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2.5">
          {c.facts.map((f) => (
            <div key={f.k} className="rounded-md bg-soft px-3 py-2.5">
              <dt className="text-[13px] text-muted">{f.k}</dt>
              <dd className="m-0 break-words font-bold">{f.v}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="m-0 text-muted">field-api sent no quantities or serials for this case.</p>
      )}
      <div className="flex flex-col gap-1.5 rounded-card border border-selected-line bg-selected-soft px-4 py-3.5">
        <div className="text-[13px] font-bold text-primary">Rule-based suggestion · not posted</div>
        <div className="font-bold">{c.suggestion.headline}</div>
        <div className="text-sm text-muted">{c.suggestion.why}</div>
        <div className="text-[13px] text-muted">
          {c.suggestion.basis} These are fixed rules, not AI; the AI assistant with sources comes in phase 6.
        </div>
      </div>
      <p
        className={cx(
          "m-0 rounded-md px-3 py-2 text-sm",
          c.sod.mayDecide === true ? "bg-ok-bg text-ok-ink" : c.sod.mayDecide === false ? "bg-warn-bg text-warn-ink" : "bg-soft text-muted",
        )}
      >
        {c.sod.text}
      </p>
      <div className="flex flex-col gap-1">
        <label htmlFor="reason" className="font-bold">
          Reason (saved with the decision)
        </label>
        <textarea
          id="reason"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          aria-invalid={reasonMissing}
          aria-describedby={reasonMissing ? "reason-err" : undefined}
          className="rounded-md border border-control bg-card px-3 py-2"
        />
        {reasonMissing ? (
          <span id="reason-err" className="text-sm font-bold text-alert-ink">
            Write a short reason first.
          </span>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="m-0 rounded-md border border-alert-line bg-alert-bg px-3 py-2 text-alert-ink">
          {error}
        </p>
      ) : null}
      {permissionNote ? <p className="m-0 text-sm text-muted">{permissionNote}</p> : null}
      <div className="flex flex-wrap gap-2.5">{buttons}</div>
    </div>
  );
}

export default function DecisionsPage() {
  const live = useLive();
  const { session } = useSession();
  const now = useNow(30000);
  const [selKey, setSelKey] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);

  const approvals = dataOf(live.approvals);
  const mismatches = dataOf(live.mismatches);
  const loading = live.approvals.status === "loading" || live.mismatches.status === "loading";
  const cases = buildCases(approvals ?? [], mismatches ?? [], session?.principalId ?? "", now);
  const sel = cases.find((c) => c.key === selKey) ?? cases[0] ?? null;
  const anyData = approvals !== undefined || mismatches !== undefined;

  return (
    <>
      <PageHeader title="Decisions" lead="Exceptions the system could not settle. A rule suggests the next step; a person decides.">
        <Freshness state={live.mismatches} />
      </PageHeader>
      {sourceProblem("Count differences", live.approvals, live.refresh.approvals)}
      {sourceProblem("Tower findings", live.mismatches, live.refresh.mismatches)}
      {outcome ? (
        <p role="status" className="m-0 rounded-card border border-line bg-ok-bg px-4 py-3 font-bold text-ok-ink">
          {outcome}
        </p>
      ) : null}
      {loading && !anyData ? (
        <LoadingState />
      ) : !anyData ? null : cases.length === 0 ? (
        <EmptyState title="No open decisions" body="Count differences beyond tolerance and tower serial mismatches appear here." />
      ) : (
        <div className="flex flex-wrap items-start gap-4">
          <div className="flex max-w-full flex-[1_1_300px] flex-col gap-2 md:max-w-[380px]" role="group" aria-label="Open cases">
            {cases.map((c) => (
              <CaseButton
                key={c.key}
                c={c}
                on={sel?.key === c.key}
                onPick={() => {
                  setSelKey(c.key);
                  setOutcome(null);
                }}
              />
            ))}
          </div>
          {sel ? (
            <Detail
              c={sel}
              onDone={(msg) => {
                setOutcome(msg);
                void live.refresh.approvals();
                void live.refresh.mismatches();
                void live.refresh.tasks();
              }}
            />
          ) : null}
        </div>
      )}
    </>
  );
}
