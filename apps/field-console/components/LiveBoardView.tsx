"use client";

import React from "react";
import { EmptyState, Freshness, PageHeader, PollView } from "@/components/ui";
import { NEEDS, useLive } from "@/components/session";
import { useNow } from "@/components/usePoll";
import { buildBoard, filterByType } from "@/lib/views/board";
import { sandboxSiteIds } from "@/lib/views/sessions";
import { dataOf } from "@/components/usePoll";

export interface LiveBoardViewProps {
  title?: string;
  lead?: string;
  /** Job types to show (receive, putaway, pick, count, audit, swap). Omitted = all. */
  types?: readonly string[];
  emptyBody?: string;
}

/** Marks work and sessions at a sandbox site (M3: test boxes at home, not real stock). */
export function SandboxBadge() {
  return (
    <span className="ml-2 inline-block rounded-full bg-warn-pill px-2 py-px align-middle text-[12px] font-bold text-warn-pillink" title="Sandbox site: test data, not real stock">
      Sandbox
    </span>
  );
}

export function LiveBoardView({
  title = "Live work",
  lead = "Updates as people scan. Blocked cards say why.",
  types,
  emptyBody = "Jobs appear here when deliveries, picks, counts or tower audits arrive from SAP or are created on the dev stack.",
}: LiveBoardViewProps) {
  const live = useLive();
  const now = useNow(5000);
  return (
    <>
      <PageHeader title={title} lead={lead}>
        <Freshness state={live.tasks} />
      </PageHeader>
      <PollView
        state={live.tasks}
        role={NEEDS.tasks.role}
        onRetry={live.refresh.tasks}
        isEmpty={(d) => filterByType(d, types).length === 0}
        empty={
          <EmptyState title="No jobs yet" body={emptyBody} />
        }
      >
        {(tasks) => {
          const cols = buildBoard(filterByType(tasks, types), now, sandboxSiteIds(dataOf(live.sites)));
          return (
            <div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
                {cols.map((col) => (
                  <section
                    key={col.id}
                    aria-labelledby={`col-${col.id}`}
                    className="flex flex-col gap-2 rounded-card bg-column p-2.5"
                  >
                    <h2 id={`col-${col.id}`} className="m-0 px-1 py-0.5 text-base font-bold">
                      {col.name} <span className="font-normal text-muted">· {col.count}</span>
                    </h2>
                    {col.note ? <p className="m-0 px-1 text-[13px] text-muted">{col.note}</p> : null}
                    {col.cards.length === 0 ? <p className="m-0 px-1 text-[13px] text-muted">Nothing here.</p> : null}
                    <ul className="m-0 flex list-none flex-col gap-2 p-0">
                      {col.cards.map((k) => (
                        <li key={k.id} className="flex flex-col gap-0.5 rounded-md border border-line bg-card px-3 py-2.5">
                          <span className="text-[15px] font-bold">
                            {k.title}
                            {k.sandbox ? <SandboxBadge /> : null}
                          </span>
                          {k.subtitle ? <span className="text-[13px] text-muted">{k.subtitle}</span> : null}
                          {k.progress ? <span className="text-[13px] text-muted">{k.progress}</span> : null}
                          {k.why ? <span className="text-[13px] font-bold text-warn-ink">{k.why}</span> : null}
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            </div>
          );
        }}
      </PollView>
    </>
  );
}
