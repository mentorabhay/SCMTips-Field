"use client";

// M3 WP5 (console): Field Assistant sessions on live data — GET /v1/assistant/sessions, the detail with its
// turns, photos, SAP documents and the CSV export (docs/design/M3_CONTRACT.md §4). Supervisor read.
import React, { useState } from "react";
import { ApiError } from "@/lib/api";
import { api } from "@/lib/client";
import { buildSessionRows, sessionDetail, sessionsSummary, type PhotoLink } from "@/lib/views/sessions";
import { SandboxBadge } from "@/components/LiveBoardView";
import { useLive, useSession } from "@/components/session";
import { dataOf, useNow, usePoll } from "@/components/usePoll";
import { cx, EmptyState, Freshness, PageHeader, Pill, PollView } from "@/components/ui";

const ROLE = "Supervisor";

/** Saves a Blob as a file (the export needs the sign-in token, so it cannot be a plain link). */
function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function DownloadCsv({ id }: { id: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            save(await api.exportAssistantSessionCsv(id), `assistant-session-${id}.csv`);
          } catch (e) {
            setError(e instanceof ApiError ? e.title : "The export did not download.");
          } finally {
            setBusy(false);
          }
        }}
        className="min-h-[40px] rounded-md border border-control bg-card px-3 font-bold text-ink hover:bg-soft disabled:opacity-60"
      >
        {busy ? "Preparing…" : "Download CSV"}
      </button>
      {error ? <span role="alert" className="text-sm text-alert-ink">{error}</span> : null}
    </span>
  );
}

function Photo({ photo }: { photo: PhotoLink }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!photo.path) return <span className="text-[13px] text-muted">Photo kept ({photo.ref})</span>;
  const path = photo.path;
  if (url) return <img src={url} alt="Photo from the glasses for this turn" className="mt-1 max-h-48 rounded-md border border-line" />;
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        className="font-bold text-primary underline"
        onClick={async () => {
          try {
            setUrl(URL.createObjectURL(await api.downloadPath(path)));
          } catch (e) {
            setError(e instanceof ApiError ? e.title : "The photo did not load.");
          }
        }}
      >
        Show photo
      </button>
      {error ? <span className="text-[13px] text-alert-ink">{error}</span> : null}
    </span>
  );
}

function Detail({ id, onClose }: { id: string; onClose: () => void }) {
  const live = useLive();
  const now = useNow(15000);
  const detail = usePoll(() => api.getAssistantSession(id), { enabled: true, key: id, intervalMs: 10000 });
  const sites = dataOf(live.sites) ?? [];
  return (
    <section aria-labelledby="session-detail" className="flex flex-col gap-3 rounded-card border border-line bg-card p-4">
      <PollView state={detail.state} role={ROLE} onRetry={detail.refresh}>
        {(s) => {
          const v = sessionDetail(s, sites, now);
          return (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <h2 id="session-detail" className="m-0 flex-1 text-lg font-bold">
                  {v.title}
                  {v.sandbox ? <SandboxBadge /> : null}
                </h2>
                <DownloadCsv id={v.id} />
                <button type="button" onClick={onClose} className="min-h-[40px] rounded-md px-3 font-bold text-primary hover:bg-soft">
                  Close
                </button>
              </div>
              <p className="m-0 text-sm text-muted">
                {v.turns.length} turns · {v.aiTurns} answered by the model · {v.rulesTurns} by the fixed rules · {v.cost} AI cost.
                Words and photos are kept 30 days.
              </p>
              <div className="text-sm">
                <b>SAP documents: </b>
                {v.documents.length ? <span className="font-mono">{v.documents.join(", ")}</span> : <span className="text-muted">none from this session</span>}
              </div>
              {v.turns.length === 0 ? (
                <p className="m-0 text-muted">No turns recorded.</p>
              ) : (
                <ol className="m-0 flex list-none flex-col gap-2 p-0">
                  {v.turns.map((t) => (
                    <li key={t.id} className="rounded-md border border-line-soft px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
                        <span className="font-bold text-ink">{t.eventLabel}</span>
                        <span>{new Date(t.atMs).toLocaleTimeString()}</span>
                        {t.ai ? <Pill tone={t.ai === "AI" ? "info" : "neutral"}>{t.ai}</Pill> : null}
                        <span>{t.cost}</span>
                        {t.latency ? <span>{t.latency}</span> : null}
                        {t.code ? <span className="font-mono">code {t.code}</span> : null}
                      </div>
                      {t.heard ? <div className="text-[15px]">Heard: “{t.heard}”</div> : null}
                      {t.said ? <div className="text-[15px] text-muted">Said: {t.said}</div> : null}
                      {t.purged ? <div className="text-[13px] text-muted">Words removed after 30 days.</div> : null}
                      {t.actions ? <div className="text-[13px] text-muted">Phone did: {t.actions}</div> : null}
                      {t.photo ? <Photo photo={t.photo} /> : null}
                    </li>
                  ))}
                </ol>
              )}
            </>
          );
        }}
      </PollView>
    </section>
  );
}

export default function SessionsPage() {
  const live = useLive();
  const { session } = useSession();
  const now = useNow(15000);
  const [siteId, setSiteId] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const sessions = usePoll(() => api.listAssistantSessions({ site_id: siteId || undefined, limit: 100 }), {
    enabled: Boolean(session),
    key: `${session?.accessToken ?? ""}|${siteId}`,
  });
  const sites = dataOf(live.sites) ?? [];
  const notThere = sessions.state.status === "error" && sessions.state.error.kind === "not_found";

  return (
    <>
      <PageHeader title="Assistant sessions" lead="What the glasses assistant heard, said and did, per work session.">
        <Freshness state={sessions.state} />
      </PageHeader>
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="session-site" className="font-bold">
          Site
        </label>
        <select
          id="session-site"
          value={siteId}
          onChange={(e) => setSiteId(e.target.value)}
          className="min-h-[44px] rounded-md border border-control bg-card px-3"
        >
          <option value="">All sites</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code}
              {s.mode === "sandbox" ? " (sandbox)" : ""}
            </option>
          ))}
        </select>
      </div>
      {notThere ? (
        <EmptyState
          title="No assistant records on this field-api yet"
          body="This field-api does not answer /v1/assistant/sessions. Sessions appear here once the assistant is installed on the PC."
        />
      ) : (
        <PollView
          state={sessions.state}
          role={ROLE}
          onRetry={sessions.refresh}
          isEmpty={(d) => d.length === 0}
          empty={<EmptyState title="No sessions yet" body="A session starts when an operator taps Start work on the phone, or puts the glasses on." />}
        >
          {(list) => {
            const rows = buildSessionRows(list, sites, now);
            return (
              <>
                <p className="m-0 text-sm text-muted">{sessionsSummary(rows, list)}</p>
                <div className="overflow-x-auto rounded-card border border-line bg-card">
                  <table className="w-full min-w-[760px] border-collapse text-left text-[15px]">
                    <caption className="sr-only">Assistant sessions, newest first</caption>
                    <thead className="bg-soft text-[13px] text-muted">
                      <tr className="border-b border-line">
                        <th scope="col" className="px-3.5 py-2.5">Started</th>
                        <th scope="col" className="px-3.5 py-2.5">Who and where</th>
                        <th scope="col" className="px-3.5 py-2.5">Length</th>
                        <th scope="col" className="px-3.5 py-2.5">Turns</th>
                        <th scope="col" className="px-3.5 py-2.5">SAP documents</th>
                        <th scope="col" className="px-3.5 py-2.5">AI cost</th>
                        <th scope="col" className="px-3.5 py-2.5"><span className="sr-only">Open</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.id} className={cx("border-b border-line-soft last:border-b-0", open === r.id ? "bg-selected-soft" : "")}>
                          <td className="px-3.5 py-2.5">
                            {r.started}
                            {r.active ? <span className="ml-2"><Pill tone="ok">Running</Pill></span> : null}
                          </td>
                          <td className="px-3.5 py-2.5">
                            <b>{r.who}</b>
                            <div className="text-[13px] text-muted">
                              {r.siteLabel}
                              {r.sandbox ? <SandboxBadge /> : null}
                            </div>
                          </td>
                          <td className="px-3.5 py-2.5">{r.duration}</td>
                          <td className="px-3.5 py-2.5">{r.turns}</td>
                          <td className="px-3.5 py-2.5 font-mono text-[13px]">{r.documents.length ? r.documents.join(", ") : "—"}</td>
                          <td className="px-3.5 py-2.5">{r.cost}</td>
                          <td className="px-3.5 py-1.5">
                            <button
                              type="button"
                              onClick={() => setOpen(open === r.id ? null : r.id)}
                              aria-expanded={open === r.id}
                              className="min-h-[40px] rounded-md border border-control bg-card px-3 font-bold text-ink hover:bg-soft"
                            >
                              {open === r.id ? "Hide" : "Turns"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            );
          }}
        </PollView>
      )}
      {open ? <Detail id={open} onClose={() => setOpen(null)} /> : null}
    </>
  );
}
