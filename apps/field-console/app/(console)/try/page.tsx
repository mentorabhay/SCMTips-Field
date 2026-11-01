"use client";

// M5-W01: "Try a look" for judges — the real look (SAM 3.1 instances, label reads, deterministic check, spoken
// answer) on a SAMPLE photo or an upload, through POST /v1/try/looks. Nothing is posted; photos are kept 24 hours.
// The page logic lives in lib/views/try.ts (tested); this file is the browser glue (canvas, speech, file input).
import React, { useEffect, useRef, useState } from "react";
import type { TryCase, TryLook } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { api } from "@/lib/client";
import {
  browserVoice,
  checkFile,
  costText,
  createSpeaker,
  findings,
  fitWithin,
  itemRows,
  lookButtonLabel,
  modeNotice,
  outlines,
  pollUntilFinal,
  proposalText,
  speakLook,
  strokeFor,
  svgPoints,
  TONE_COLOR,
  TRY_CASES,
  TRY_SAMPLES,
  tryRequest,
  type TrySample,
} from "@/lib/views/try";
import { useSession } from "@/components/session";
import { cx, ForbiddenState, PageHeader, Pill } from "@/components/ui";

const ROLE = "Operator, Supervisor or Viewer";

/** The photo scaled in the browser to at most 1600 px on its long side, re-encoded as JPEG (drops EXIF, e.g. GPS). */
async function downscale(blob: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(blob);
  const size = fitWithin(bitmap.width, bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = size.width;
  canvas.height = size.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser cannot scale photos.");
  ctx.drawImage(bitmap, 0, 0, size.width, size.height);
  bitmap.close();
  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("The photo could not be prepared."))), "image/jpeg", 0.85),
  );
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

type Source = { kind: "sample"; sample: TrySample } | { kind: "file"; file: File };

function Banner() {
  return (
    <div role="note" className="flex flex-wrap items-center gap-2 rounded-card border border-warn-line bg-warn-bg px-4 py-3 text-[15px]">
      <Pill tone="warn">SAMPLE</Pill>
      <span>
        <b>Nothing is posted.</b> Photos and label text are kept 24 hours, then deleted. field-api blurs any face it finds before a model sees the
        photo — still, please do not photograph people.
      </span>
    </div>
  );
}

function PhotoWithOutlines({ look, photoUrl }: { look: TryLook; photoUrl: string }) {
  const w = look.image.width ?? 1280;
  const h = look.image.height ?? 960;
  const s = strokeFor(w);
  return (
    <figure className="m-0">
      <div className="relative w-full overflow-hidden rounded-card border border-line bg-soft">
        <img src={photoUrl} alt="The photo the look was run on" className="block h-auto w-full" />
        <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
          {outlines(look).map((o) => (
            <g key={o.n}>
              <polygon points={svgPoints(o.points)} fill="none" stroke={TONE_COLOR[o.tone]} strokeWidth={s.stroke} />
              <rect x={o.label.x} y={o.label.y} width={s.badge} height={s.badge} rx={s.stroke} fill={TONE_COLOR[o.tone]} />
              <text x={o.label.x + s.badge / 2} y={o.label.y + s.badge * 0.72} fontSize={s.font} fontWeight={700} textAnchor="middle" fill="#fff">
                {o.n}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <figcaption className="mt-1 flex flex-wrap gap-3 text-[13px] text-muted">
        <span><span style={{ color: TONE_COLOR.good }}>■</span> good</span>
        <span><span style={{ color: TONE_COLOR.damaged }}>■</span> damaged</span>
        <span><span style={{ color: TONE_COLOR.pending }}>■</span> labels being read</span>
        {look.image.faces_blurred ? <span>{look.image.faces_blurred} face(s) blurred by field-api</span> : null}
      </figcaption>
    </figure>
  );
}

function Result({ look, photoUrl, spoken, stillReading, onSpeak }: { look: TryLook; photoUrl: string | null; spoken: string[]; stillReading: boolean; onSpeak: () => void }) {
  const notice = modeNotice(look);
  const rows = itemRows(look);
  const c = look.counts;
  return (
    <section aria-labelledby="try-result" className="flex flex-col gap-4">
      <h2 id="try-result" className="m-0 text-xl font-bold">
        {look.final === false ? (stillReading ? "Still reading the labels" : "Counted — reading the labels…") : "The look"}
        <span className="ml-2 align-middle">
          <Pill tone={look.source === "model" ? "ok" : look.source === "partial" ? "info" : "warn"}>{look.source === "rules" ? "rules mode" : look.source}</Pill>
        </span>
      </h2>
      {notice ? (
        <div role="status" className={cx("rounded-card border px-4 py-3", notice.tone === "warn" ? "border-warn-line bg-warn-bg" : "border-line bg-soft")}>
          <b>{notice.title}.</b> {notice.body}
        </div>
      ) : null}
      {stillReading ? <p className="m-0 text-muted">No final answer within 60 seconds. The numbers below are the count only.</p> : null}
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        {photoUrl ? <PhotoWithOutlines look={look} photoUrl={photoUrl} /> : <p className="text-muted">The photo is no longer kept.</p>}
        <div className="flex flex-col gap-3">
          <div className="rounded-card border border-line bg-card p-4" aria-live="polite">
            <div className="text-[13px] font-bold uppercase text-muted">The glasses say</div>
            {spoken.length ? spoken.map((t, i) => <p key={i} className="m-0 mt-1 text-[17px]">“{t}”</p>) : <p className="m-0 mt-1 text-[17px]">“{look.say}”</p>}
            <button type="button" onClick={onSpeak} className="mt-2 min-h-[40px] rounded-md border border-control bg-card px-3 font-bold text-ink hover:bg-soft">
              Speak again
            </button>
          </div>
          <dl className="m-0 grid grid-cols-4 gap-2 text-center">
            {([["Expected", c.expected], ["Seen", c.seen], ["Damaged", c.damaged], ["Good", c.good]] as const).map(([k, val]) => (
              <div key={k} className="rounded-md border border-line bg-card px-2 py-2">
                <dt className="text-[13px] text-muted">{k}</dt>
                <dd className="m-0 text-2xl font-bold">{val ?? "—"}</dd>
              </div>
            ))}
          </dl>
          <ul className="m-0 flex list-disc flex-col gap-1 pl-5">
            {findings(look).map((f, i) => <li key={i}>{f}</li>)}
          </ul>
          <p className="m-0 rounded-md bg-soft px-3 py-2 font-bold">{proposalText(look)}</p>
        </div>
      </div>
      {rows.length ? (
        <div className="overflow-x-auto rounded-card border border-line bg-card">
          <table className="w-full min-w-[560px] border-collapse text-left text-[15px]">
            <caption className="sr-only">Each item the look found, numbered as on the photo</caption>
            <thead className="bg-soft text-[13px] text-muted">
              <tr className="border-b border-line">
                <th scope="col" className="px-3 py-2">#</th>
                <th scope="col" className="px-3 py-2">Condition</th>
                <th scope="col" className="px-3 py-2">Label read</th>
                <th scope="col" className="px-3 py-2">Check</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.n} className="border-b border-line-soft last:border-b-0">
                  <td className="px-3 py-2 font-bold">{r.n}</td>
                  <td className={cx("px-3 py-2", r.damaged ? "font-bold text-alert-ink" : "")}>{r.condition}</td>
                  <td className="px-3 py-2">{r.label}</td>
                  <td className="px-3 py-2">{r.flags.length ? r.flags.join("; ") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <details className="rounded-card border border-line bg-card px-4 py-3 text-[15px]">
        <summary className="cursor-pointer font-bold">Model calls ({look.models.length}) · {costText(look.models)}</summary>
        <ul className="m-0 mt-2 flex list-none flex-col gap-1 p-0 font-mono text-[13px]">
          {look.models.map((m, i) => (
            <li key={i}>
              {m.model} · {m.purpose} · {m.latency_ms} ms · ${m.cost_usd.toFixed(4)} · {m.outcome}
            </li>
          ))}
          {look.reasons.length ? <li>reasons: {look.reasons.join(", ")}</li> : null}
        </ul>
      </details>
    </section>
  );
}

export default function TryPage() {
  const { session, can } = useSession();
  const [caseId, setCaseId] = useState<TryCase>("grocery");
  const [units, setUnits] = useState(String(TRY_CASES.grocery.defaultUnits));
  const [pieces, setPieces] = useState(String(TRY_CASES.grocery.defaultPieces));
  const [windowDays, setWindowDays] = useState(String(TRY_CASES.pharmacy.defaultWindowDays));
  const [source, setSource] = useState<Source | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [look, setLook] = useState<TryLook | null>(null);
  const [stored, setStored] = useState<string | null>(null);
  const [spoken, setSpoken] = useState<string[]>([]);
  const [stillReading, setStillReading] = useState(false);
  const run = useRef(0);
  const speaker = useRef<ReturnType<typeof createSpeaker> | null>(null);

  useEffect(() => {
    const voice = typeof window !== "undefined" ? browserVoice(window.speechSynthesis, (t) => new SpeechSynthesisUtterance(t)) : null;
    speaker.current = voice ? createSpeaker(voice) : null;
    return () => {
      run.current++;
      speaker.current?.stop();
    };
  }, []);
  useEffect(() => () => { if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => () => { if (stored) URL.revokeObjectURL(stored); }, [stored]);

  if (!session) return null;
  if (!can("field.try.use")) return <ForbiddenState role={ROLE} />;

  const info = TRY_CASES[caseId];
  const chooseCase = (c: TryCase) => {
    setCaseId(c);
    setUnits(String(TRY_CASES[c].defaultUnits));
    if (source?.kind === "sample" && source.sample.case !== c) {
      setSource(null);
      setPreview(null);
    }
  };
  const chooseSample = (s: TrySample) => {
    if (s.case !== caseId) chooseCase(s.case);
    setSource({ kind: "sample", sample: s });
    setPreview(s.src);
    setError(null);
  };
  const chooseFile = (f: File | undefined) => {
    if (!f) return;
    const problem = checkFile(f);
    if (problem) {
      setError(problem);
      return;
    }
    setSource({ kind: "file", file: f });
    setPreview(URL.createObjectURL(f));
    setError(null);
  };

  const start = async () => {
    const req = tryRequest(caseId, Number(units), { pieces: Number(pieces), windowDays: Number(windowDays) });
    if (!req.ok) return setError(req.error);
    if (!source) return setError("Pick a SAMPLE photo or upload one.");
    const mine = ++run.current;
    speaker.current?.stop();
    setBusy(true);
    setError(null);
    setLook(null);
    setStored(null);
    setSpoken([]);
    setStillReading(false);
    try {
      const raw = source.kind === "sample" ? await (await fetch(source.sample.src)).blob() : source.file;
      const photo = await downscale(raw);
      const first = await api.createTryLook(photo, req.request, source.kind === "sample" ? source.sample.fileName : "upload.jpg");
      if (mine !== run.current) return;
      setLook(first);
      if (first.try?.photo_url) {
        api.getTryPhoto(first.look_id).then((b) => mine === run.current && setStored(URL.createObjectURL(b))).catch(() => undefined);
      }
      const waitFinal = () =>
        pollUntilFinal(first, {
          get: (id) => api.getTryLook(id),
          sleep,
          now: () => Date.now(),
          onUpdate: (l) => mine === run.current && setLook(l),
          cancelled: () => mine !== run.current,
        });
      const say = speaker.current;
      let result: { look: TryLook; final: boolean };
      if (say) {
        const before = say.spoken.length;
        const track = setInterval(() => mine === run.current && setSpoken(say.spoken.slice(before)), 300);
        result = await speakLook(first, waitFinal, say).finally(() => clearInterval(track));
        if (mine === run.current) setSpoken(say.spoken.slice(before));
      } else {
        result = await waitFinal();
        setSpoken([first.say, ...(result.final && first.final === false && result.look.say_next ? [result.look.say_next] : [])]);
      }
      if (mine !== run.current) return;
      setLook(result.look);
      setStillReading(!result.final);
    } catch (e) {
      if (mine === run.current) setError(e instanceof ApiError ? [e.title, e.detail].filter(Boolean).join(" ") : e instanceof Error ? e.message : "The look did not run.");
    } finally {
      if (mine === run.current) setBusy(false);
    }
  };

  const speakAgain = () => {
    if (!look || !speaker.current) return;
    speaker.current.stop();
    void speaker.current.say(look.say);
  };

  const field = "min-h-[44px] w-28 rounded-md border border-control bg-card px-3";
  return (
    <>
      <PageHeader title="Try a look" lead="One photo of a delivery: Field counts it with Meta's SAM 3.1, reads the labels with Muse Spark, checks the numbers with fixed rules and speaks the answer — as the glasses do." />
      <Banner />
      <section aria-labelledby="try-setup" className="flex flex-col gap-4 rounded-card border border-line bg-card p-4">
        <h2 id="try-setup" className="m-0 text-lg font-bold">1. The delivery</h2>
        <fieldset className="m-0 flex flex-wrap gap-3 border-0 p-0">
          <legend className="sr-only">Test case</legend>
          {(Object.keys(TRY_CASES) as TryCase[]).map((c) => (
            <label key={c} className={cx("flex min-h-[44px] cursor-pointer items-center gap-2 rounded-md border px-3", caseId === c ? "border-primary bg-selected" : "border-control")}>
              <input type="radio" name="try-case" checked={caseId === c} onChange={() => chooseCase(c)} />
              <span><b>{TRY_CASES[c].title}</b> <span className="text-[13px] text-muted">({TRY_CASES[c].where})</span></span>
            </label>
          ))}
        </fieldset>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 font-bold">
            Expected {info.noun}
            <input type="number" min={1} max={200} value={units} onChange={(e) => setUnits(e.target.value)} className={field} />
          </label>
          {caseId === "grocery" ? (
            <label className="flex flex-col gap-1 font-bold">
              Pieces per pack
              <input type="number" min={1} max={1000} value={pieces} onChange={(e) => setPieces(e.target.value)} className={field} />
            </label>
          ) : (
            <label className="flex flex-col gap-1 font-bold">
              Expiry window (days)
              <input type="number" min={0} max={3650} value={windowDays} onChange={(e) => setWindowDays(e.target.value)} className={field} />
            </label>
          )}
        </div>
        <h2 className="m-0 text-lg font-bold">2. The photo</h2>
        <div className="flex flex-wrap gap-3">
          {TRY_SAMPLES.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => chooseSample(s)}
              aria-pressed={source?.kind === "sample" && source.sample.id === s.id}
              className={cx("flex w-[220px] flex-col gap-1 rounded-md border p-2 text-left", source?.kind === "sample" && source.sample.id === s.id ? "border-primary bg-selected" : "border-control bg-card hover:bg-soft")}
            >
              <img src={s.src} alt="" className="h-[120px] w-full rounded object-cover" />
              <span className="font-bold">SAMPLE · {s.title}</span>
              <span className="text-[13px] text-muted">{TRY_CASES[s.case].title}. {s.note}</span>
            </button>
          ))}
          <label className="flex w-[220px] cursor-pointer flex-col justify-center gap-1 rounded-md border border-dashed border-control p-3 hover:bg-soft">
            <span className="font-bold">Upload a photo</span>
            <span className="text-[13px] text-muted">JPEG or PNG, up to 5 MB. Items in one layer, seen from above. Scaled to 1600 px in your browser.</span>
            <input type="file" accept="image/jpeg,image/png" className="text-[13px]" onChange={(e) => chooseFile(e.target.files?.[0])} />
          </label>
        </div>
        {preview && !look ? <img src={preview} alt="The chosen photo" className="max-h-[280px] w-auto self-start rounded-md border border-line" /> : null}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void start()}
            disabled={busy}
            className="min-h-[48px] rounded-md bg-primary px-5 text-lg font-bold text-white hover:bg-primary-hover disabled:opacity-60"
          >
            {lookButtonLabel(busy, look)}
          </button>
          {error ? <span role="alert" className="font-bold text-alert-ink">{error}</span> : null}
        </div>
      </section>
      {look ? <Result look={look} photoUrl={stored ?? preview} spoken={spoken} stillReading={stillReading} onSpeak={speakAgain} /> : null}
    </>
  );
}
