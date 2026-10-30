"use client";

import React from "react";
import Link from "next/link";
import { NEEDS, useLive, useSession } from "@/components/session";
import { SafetyBannerView } from "@/components/SafetyBannerView";
import { dataOf, toAvail, useNow } from "@/components/usePoll";
import { cx, ErrorState, PageHeader } from "@/components/ui";
import { buildCases, type DecisionCase } from "@/lib/views/decisions";
import { decideCard, devicesCard, postCard, workCard, type Avail, type CardTone } from "@/lib/views/now";
import { safetyBanners } from "@/lib/views/safety";

const VALUE_TONE: Record<CardTone, string> = {
  ink: "text-ink",
  warn: "text-warn-number",
  ok: "text-ok-dot",
  muted: "text-muted",
};

export default function RightNowPage() {
  const live = useLive();
  const { session } = useSession();
  const now = useNow(5000);
  const principal = session?.principalId ?? "";

  const visits = live.visits;
  const banners = safetyBanners(dataOf(visits)?.visits ?? [], now);

  const a = toAvail(live.approvals, "Supervisor");
  const m = toAvail(live.mismatches, "Supervisor");
  let cases: Avail<DecisionCase[]>;
  if ("data" in a || "data" in m) {
    cases = { data: buildCases("data" in a ? a.data : [], "data" in m ? m.data : [], principal, now) };
  } else if ("loading" in a || "loading" in m) {
    cases = { loading: true };
  } else {
    cases = { error: a.error };
  }
  const partial = ("data" in a) !== ("data" in m) && !("loading" in a) && !("loading" in m);

  const cards = [
    workCard(toAvail(live.tasks, NEEDS.tasks.role)),
    decideCard(cases, now),
    postCard(toAvail(live.queues, NEEDS.queues.role)),
    devicesCard(toAvail(live.devices, NEEDS.devices.role)),
  ];
  if (partial && "data" in cases) {
    const missing = "data" in a ? "tower findings" : "count differences";
    cards[1] = { ...cards[1], note: `${cards[1].note} · ${missing} not available` };
  }

  return (
    <>
      <PageHeader title="Right now" lead="What needs your attention first." />

      <section aria-label="People on a structure" className="flex flex-col gap-3">
        {visits.status === "error" && visits.error.kind !== "forbidden" ? (
          <ErrorState error={visits.error} onRetry={live.refresh.visits} />
        ) : null}
        {banners.map((b) => (
          <SafetyBannerView key={b.visitId} banner={b} mode="link" />
        ))}
        {visits.status === "ok" && banners.length === 0 ? (
          <p className="m-0 rounded-card border border-line bg-card px-4 py-3 text-muted">Nobody is on a structure right now.</p>
        ) : null}
      </section>

      <section aria-label="Summary" className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3.5">
        {cards.map((c) => (
          <Link
            key={c.id}
            href={c.href}
            className="flex flex-col gap-1 rounded-card border border-line bg-card px-[18px] py-4 text-ink no-underline hover:border-primary hover:text-ink"
          >
            <span className="text-sm text-muted">{c.label}</span>
            <span className={cx("text-[32px] font-bold leading-tight", VALUE_TONE[c.tone])}>{c.value}</span>
            <span className="text-sm text-muted">{c.note}</span>
          </Link>
        ))}
      </section>
    </>
  );
}
