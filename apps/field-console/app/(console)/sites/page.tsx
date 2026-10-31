"use client";

import React from "react";
import Link from "next/link";
import type { AuditProgress, Task } from "@/lib/api";
import { api } from "@/lib/client";
import { buildSiteRows, type TagTone } from "@/lib/views/sites";
import { safetyBanners } from "@/lib/views/safety";
import { NEEDS, useLive, useSession } from "@/components/session";
import { SafetyBannerView } from "@/components/SafetyBannerView";
import { SandboxBadge } from "@/components/LiveBoardView";
import { isSandbox } from "@/lib/views/sessions";
import { dataOf, useNow, usePoll } from "@/components/usePoll";
import { cx, EmptyState, ErrorState, Freshness, PageHeader, Pill, PollView, type PillTone } from "@/components/ui";

const TAG_TONE: Record<TagTone, PillTone> = {
  alert: "alert",
  climb: "warn",
  done: "ok",
  progress: "info",
  planned: "neutral",
  neutral: "neutral",
};

export default function SitesPage() {
  const live = useLive();
  const { session, can } = useSession();
  const now = useNow(5000);
  const sites = usePoll(() => api.listSites(), { enabled: can(NEEDS.sites.permission), key: session?.accessToken });

  const auditTasks: Task[] = (dataOf(live.tasks) ?? []).filter((t) => t.type === "audit");
  const auditKey = auditTasks.map((t) => t.id).sort().join(",");
  const progress = usePoll(
    async () => {
      const res = await Promise.allSettled(auditTasks.map((t) => api.getAuditProgress(t.id)));
      const out: Record<string, AuditProgress | null> = {};
      auditTasks.forEach((t, i) => {
        const r = res[i];
        out[t.id] = r.status === "fulfilled" ? r.value : null;
      });
      return out;
    },
    { enabled: auditTasks.length > 0, key: auditKey },
  );
  const progressById = dataOf(progress.state) ?? {};
  const visits = dataOf(live.visits)?.visits ?? [];
  const alerts = safetyBanners(visits, now).filter((b) => b.needsAck);

  return (
    <>
      <PageHeader title="Sites and towers" lead="Audit progress per sector, and who is on a structure.">
        <Freshness state={live.visits} />
      </PageHeader>

      {live.visits.status === "error" && live.visits.error.kind !== "forbidden" ? (
        <ErrorState error={live.visits.error} onRetry={live.refresh.visits} />
      ) : null}
      {alerts.map((b) => (
        <SafetyBannerView key={b.visitId} banner={b} mode="ack" onAcked={() => void live.refresh.visits()} />
      ))}
      {live.tasks.status === "error" && live.tasks.error.kind !== "forbidden" ? (
        <ErrorState error={live.tasks.error} onRetry={live.refresh.tasks} />
      ) : null}

      <PollView
        state={sites.state}
        role={NEEDS.sites.role}
        onRetry={sites.refresh}
        isEmpty={(d) => d.length === 0 && visits.length === 0 && auditTasks.length === 0}
        empty={
          <EmptyState
            title="No sites yet"
            body="Sites appear here after your administrator adds them or they sync from the ERP."
            action={<Link href="/status" className="font-bold">View system status</Link>}
          />
        }
      >
        {(list) => {
          const rows = buildSiteRows(
            list,
            auditTasks.map((t) => ({ task: t, progress: progressById[t.id] ?? null })),
            visits,
            now,
          );
          return (
            <ul className="m-0 list-none overflow-hidden rounded-card border border-line bg-card p-0">
              {rows.map((s) => (
                <li key={s.siteId} className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-line-soft px-[18px] py-3.5 last:border-b-0">
                  <div className="min-w-0 flex-[1_1_220px]">
                    <Link href={`/sites/${encodeURIComponent(s.siteId)}/towers`} className="font-mono font-bold">
                      {s.code}
                    </Link>
                    {isSandbox(list.find((x) => x.id === s.siteId)) ? <SandboxBadge /> : null}
                    {s.name && s.name !== s.code ? <div className="text-sm">{s.name}</div> : null}
                    <div className="text-sm text-muted">{s.who}</div>
                  </div>
                  <div className="min-w-0 flex-[2_1_320px]">
                    {s.sectors.length ? (
                      <div className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-2.5">
                        {s.sectors.map((x) => (
                          <div key={x.label}>
                            <div className="text-[13px] text-muted">
                              {x.label} · {x.text}
                            </div>
                            <div
                              role="progressbar"
                              aria-label={`${x.label}: ${x.text}`}
                              aria-valuemin={0}
                              aria-valuemax={100}
                              aria-valuenow={x.pct}
                              className="h-2 overflow-hidden rounded bg-column"
                            >
                              <div className={cx("h-2", x.complete ? "bg-ok-dot" : "bg-primary")} style={{ width: `${x.pct}%` }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-sm text-muted">{s.auditNote ?? (s.kind === "warehouse" ? "Warehouse · no tower audit" : "No audit open for this site")}</span>
                    )}
                  </div>
                  <div className="flex-none">
                    <Pill tone={TAG_TONE[s.tag.tone]}>{s.tag.text}</Pill>
                  </div>
                </li>
              ))}
            </ul>
          );
        }}
      </PollView>
    </>
  );
}
