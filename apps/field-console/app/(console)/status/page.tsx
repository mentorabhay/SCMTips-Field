"use client";

import React from "react";
import { api } from "@/lib/client";
import { aiChecks, statusChecks, summaryLine, toneWord, type CheckCard, type CheckTone } from "@/lib/views/system";
import { NEEDS, useSession } from "@/components/session";
import { dataOf, usePoll } from "@/components/usePoll";
import { cx, ErrorState, Freshness, PageHeader, PollView } from "@/components/ui";

const DOT: Record<CheckTone, string> = { ok: "bg-ok-dot", warn: "bg-warn-line", bad: "bg-danger", unknown: "bg-unknown" };

function Checks({ cards }: { cards: CheckCard[] }) {
  return (
    <ul className="m-0 grid list-none grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-3 p-0">
      {cards.map((c) => (
        <li key={c.name} className="flex items-start gap-3 rounded-card border border-line bg-card px-4 py-3.5">
          <span aria-hidden="true" className={cx("mt-1.5 h-3 w-3 flex-none rounded-full", DOT[c.tone])} />
          <div>
            <div className="font-bold">
              {c.name} <span className="sr-only">({toneWord(c.tone)})</span>
            </div>
            <div className="text-sm text-muted">{c.state}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function SystemStatusPage() {
  const { session, can } = useSession();
  const enabled = can(NEEDS.system.permission);
  // The ready checks are cheap; refresh them every 30 s rather than every 5 s.
  const status = usePoll(() => api.getSystemStatus(), { enabled, key: session?.accessToken, intervalMs: 30000 });
  const ai = usePoll(() => api.getAiUsage(), { enabled, key: session?.accessToken, intervalMs: 60000 });
  const aiData = dataOf(ai.state);

  return (
    <>
      <PageHeader title="System status" lead="Is everything connected? Checked every 30 seconds.">
        <Freshness state={status.state} />
      </PageHeader>
      <PollView state={status.state} role={NEEDS.system.role} onRetry={status.refresh}>
        {(s) => {
          const cards = [
            { name: "SCMTips sign-in", state: "Signed in · field-api accepted your token", tone: "ok" as const },
            ...statusChecks(s),
            ...(aiData ? aiChecks(aiData) : []),
          ];
          return (
            <>
              <p role="status" className={cx("m-0 font-bold", s.ready && summaryLine(cards) === "All checks passed" ? "text-ok-ink" : "text-warn-ink")}>
                {summaryLine(cards)}
              </p>
              <Checks cards={cards} />
              {ai.state.status === "error" && ai.state.error.kind !== "forbidden" ? <ErrorState error={ai.state.error} onRetry={ai.refresh} /> : null}
            </>
          );
        }}
      </PollView>
    </>
  );
}
