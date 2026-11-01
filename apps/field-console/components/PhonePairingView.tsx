"use client";

/**
 * "Sign in your phone" (M5-L03, contract §8): a QR of the App Link `https://app.scmtips.com/pair?code=<code>`, the
 * code in text under it, a countdown to its end and "New code". The code comes from this console's server
 * (lib/phonePairing.ts), which asks the SCMTIPS core with the signed-in person's core token; the page never sees a
 * token. The development sign-in (fake-core) has no core token, so the page says it needs SCMTIPS sign-in.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { config } from "@/lib/config";
import { countdownText, newPhonePairing, PairingError, PHONE_STEPS, secondsLeft, spacedCode, type PhonePairing } from "@/lib/phonePairingClient";
import { QrCode } from "./QrCode";
import { useSession } from "./session";
import { useNow } from "./usePoll";
import { Button, Card, PageHeader } from "./ui";

function Steps() {
  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0">
      {PHONE_STEPS.map((s, i) => (
        <li key={s} className="flex items-start gap-3">
          <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary font-bold text-white">
            {i + 1}
          </span>
          <span className="pt-1 text-lg">{s}</span>
        </li>
      ))}
    </ol>
  );
}

function NeedsCoreSignIn() {
  return (
    <Card className="flex flex-col items-start gap-2 p-5">
      <h2 className="m-0 text-xl font-bold">This needs SCMTIPS sign-in</h2>
      <p className="m-0">
        A phone can be signed in from here only when you signed in to this console with your SCMTIPS account.
        {config.devSignIn ? " You are using the development sign-in, which has no SCMTIPS account behind it." : ""}
      </p>
      {config.devSignIn ? (
        <p className="m-0 text-sm text-muted">
          On the dev stack, pair a phone with the QR code from <code>stack pair</code> instead.
        </p>
      ) : null}
    </Card>
  );
}

function CodeCard() {
  const [pairing, setPairing] = useState<PhonePairing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [announce, setAnnounce] = useState("");
  const now = useNow(1000);
  const started = useRef(false);

  const fetchCode = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const p = await newPhonePairing((input, init) => fetch(input, init), Date.now());
      setPairing(p);
      setAnnounce(`New code ready: ${spacedCode(p.code)}.`);
    } catch (e) {
      setPairing(null);
      setError(e instanceof PairingError ? e.message : "No code was made. Try again.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void fetchCode();
  }, [fetchCode]);

  const ended = pairing ? secondsLeft(pairing.expiresAtMs, now) <= 0 : false;
  useEffect(() => {
    if (ended) setAnnounce("This code has ended. Get a new code.");
  }, [ended]);

  return (
    <Card className="flex flex-col items-center gap-4 p-5 sm:p-6">
      <p className="sr-only" role="status" aria-live="polite">
        {announce}
      </p>
      {pairing && !ended ? (
        <>
          <div className="rounded-card border border-line bg-white p-2">
            <QrCode text={pairing.link} label={`QR code that signs your phone in. Code ${spacedCode(pairing.code)}`} />
          </div>
          <div className="flex flex-col items-center gap-1">
            <span className="text-sm text-muted">Or type this code in the app</span>
            <span className="font-mono text-3xl font-bold tracking-[0.15em]" data-testid="pairing-code">
              {spacedCode(pairing.code)}
            </span>
            <span className="text-muted" data-testid="pairing-countdown">
              {countdownText(pairing.expiresAtMs, now)}
            </span>
          </div>
        </>
      ) : (
        <div className="flex aspect-square w-full max-w-[280px] items-center justify-center rounded-card border-2 border-dashed border-line p-4 text-center text-muted">
          {busy ? "Getting a code…" : ended ? "This code has ended. Get a new code." : error ? "No code yet." : "Getting a code…"}
        </div>
      )}
      {error ? (
        <p role="alert" className="m-0 w-full rounded-md border border-alert-line bg-alert-bg px-3 py-2 text-alert-ink">
          {error}
        </p>
      ) : null}
      <Button variant={ended || error ? "primary" : "secondary"} onClick={() => void fetchCode()} disabled={busy}>
        {busy ? "Getting a code…" : "New code"}
      </Button>
      <p className="m-0 max-w-[340px] text-center text-sm text-muted">
        The code signs a phone in as you, once. Show it only to your own phone.
      </p>
    </Card>
  );
}

export function PhonePairingView({ coreSignInEnabled, justSignedIn }: { coreSignInEnabled: boolean; justSignedIn: boolean }) {
  const { session } = useSession();
  const viaCore = coreSignInEnabled && session?.transport === "cookie";
  return (
    <>
      {justSignedIn && viaCore ? (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line bg-ok-bg px-4 py-3 text-ok-ink">
          <span className="font-bold">You are signed in{session?.displayName ? ` as ${session.displayName}` : ""}.</span>
          <Link href="/" className="inline-flex min-h-[44px] items-center rounded-md bg-primary px-4 font-bold text-white no-underline hover:bg-primary-hover hover:text-white">
            Go to the console
          </Link>
        </div>
      ) : null}
      <PageHeader title="Sign in your phone" lead="Scan this code with SCMTips Field to sign your phone in as you, without typing a password." />
      {viaCore ? (
        <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
          <CodeCard />
          <Card className="flex flex-col gap-4 p-5 sm:p-6">
            <h2 className="m-0 text-xl font-bold">How</h2>
            <Steps />
          </Card>
        </div>
      ) : (
        <NeedsCoreSignIn />
      )}
    </>
  );
}
