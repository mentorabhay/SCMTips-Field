"use client";

import React from "react";

export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-start gap-3 p-6">
      <h1 className="m-0 text-2xl font-bold">This page stopped working</h1>
      <p role="alert" className="m-0 rounded-card border border-alert-line bg-alert-bg p-4 text-alert-ink">
        {error.message || "Something went wrong while showing this page."}
      </p>
      <button
        type="button"
        onClick={() => reset()}
        className="min-h-[44px] rounded-md bg-primary px-4 font-bold text-white hover:bg-primary-hover"
      >
        Try again
      </button>
    </div>
  );
}
