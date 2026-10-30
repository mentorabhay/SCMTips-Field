"use client";

import React, { useState } from "react";
import { ApiError, type PostingJob } from "@/lib/api";
import { api } from "@/lib/client";
import { buildQueueRows, type QueueTone } from "@/lib/views/postings";
import { NEEDS, useLive, useSession } from "@/components/session";
import { dataOf, useNow, usePoll } from "@/components/usePoll";
import { Button, EmptyState, Freshness, PageHeader, PollView } from "@/components/ui";

const MSG_TONE: Record<QueueTone, string> = { ok: "text-ok-ink", blocked: "text-warn-ink", busy: "text-muted" };

function RetryButton({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        variant="primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setErr(null);
          setMsg(null);
          try {
            await api.retryPostingJob(jobId);
            setMsg("Retry queued. The worker picks it up within seconds.");
            onDone();
          } catch (e) {
            setErr(e instanceof ApiError ? e.title : "Retry was not accepted.");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Retrying…" : "Retry now"}
      </Button>
      {msg ? <span role="status" className="text-sm text-ok-ink">{msg}</span> : null}
      {err ? <span role="alert" className="text-sm font-bold text-alert-ink">{err}</span> : null}
    </div>
  );
}

export default function PostingsPage() {
  const live = useLive();
  const { can } = useSession();
  const now = useNow(5000);
  const queues = dataOf(live.queues) ?? [];
  const blockedKeys = queues.filter((q) => q.is_blocked).map((q) => q.queue_key).sort();
  const jobs = usePoll(
    async () => {
      const res = await Promise.allSettled(blockedKeys.map((k) => api.listQueueJobs(k)));
      const out: Record<string, PostingJob[] | null> = {};
      blockedKeys.forEach((k, i) => {
        const r = res[i];
        out[k] = r.status === "fulfilled" ? r.value : null;
      });
      return out;
    },
    { enabled: blockedKeys.length > 0, key: blockedKeys.join("|") },
  );
  const jobsByQueue = dataOf(jobs.state) ?? {};
  const jobsLoading = jobs.state.status === "loading";
  const canRetry = can("field.queue.manage");

  return (
    <>
      <PageHeader title="Postings to SAP" lead="Each document posts once, in order. A blocked queue waits for you; the others keep going.">
        <Freshness state={live.queues} />
      </PageHeader>
      <PollView
        state={live.queues}
        role={NEEDS.queues.role}
        onRetry={live.refresh.queues}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="Nothing has been posted yet" body="Receipts, goods issues and count differences appear here once a job is finished on a phone." />}
      >
        {(list) => {
          const rows = buildQueueRows(list, jobsByQueue, now);
          return (
            <ul className="m-0 list-none overflow-hidden rounded-card border border-line bg-card p-0">
              {rows.map((q) => (
                <li key={q.key} className="flex flex-wrap items-center gap-x-5 gap-y-2.5 border-b border-line-soft px-[18px] py-3.5 last:border-b-0">
                  <div className="min-w-0 flex-[1_1_260px]">
                    <div className="font-bold">{q.name}</div>
                    <div className="text-sm text-muted">{q.detail}</div>
                  </div>
                  <div className={`min-w-0 flex-[2_1_280px] text-sm ${MSG_TONE[q.tone]}`}>
                    {q.blocked && jobsLoading && !jobsByQueue[q.key] ? "Loading the failed job…" : q.message}
                  </div>
                  {q.blocked && q.headJobId ? (
                    canRetry ? (
                      <RetryButton
                        jobId={q.headJobId}
                        onDone={() => {
                          void live.refresh.queues();
                          void jobs.refresh();
                        }}
                      />
                    ) : (
                      <span className="text-sm text-muted">Retry needs the Supervisor role.</span>
                    )
                  ) : null}
                </li>
              ))}
            </ul>
          );
        }}
      </PollView>
    </>
  );
}
