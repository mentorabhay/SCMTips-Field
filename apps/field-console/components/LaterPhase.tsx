import React from "react";

/** A clearly labelled placeholder for a view that a later phase builds. It shows no data. */
export function LaterPhase({ title, phase, text }: { title: string; phase: string; text: string }) {
  return (
    <>
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-[26px] font-bold leading-tight sm:text-[30px]">{title}</h1>
        <p className="m-0 text-muted">{text}</p>
      </div>
      <div className="rounded-card border-2 border-dashed border-control bg-card p-7 text-muted">
        <b className="text-ink">Later phase ({phase}).</b> Not built yet: this page has no data and no actions. It will use the
        same patterns as Decisions and Live work.
      </div>
    </>
  );
}
