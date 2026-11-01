"use client";

/** The console's login page (client part). app/(auth)/login/page.tsx decides on the server which sign-ins to show. */
import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { api, sessionStore } from "@/lib/client";
import { config } from "@/lib/config";
import { coreSignIn, CoreSignInError } from "@/lib/coreSignInClient";
import { DEV_ROLES, devSignIn, validateSignIn, type DevRole } from "@/lib/signin";

function Brand() {
  return (
    <div className="flex items-center gap-2.5 text-lg font-bold">
      <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-primary">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 7l9-4 9 4v10l-9 4-9-4z" />
          <path d="M3 7l9 4 9-4" />
          <path d="M12 11v10" />
        </svg>
      </span>
      SCMTips Field
    </div>
  );
}

function CoreSignInNotBuilt() {
  return (
    <div className="flex flex-col gap-3">
      <h1 className="m-0 text-2xl font-bold">Sign in</h1>
      <p className="m-0">
        Sign-in through SCMTips core is not connected to this console yet. Ask your administrator for access.
      </p>
      <p className="m-0 text-sm text-muted">
        On a development PC, start the console with <code>NEXT_PUBLIC_DEV_SIGNIN=1</code> to use the development sign-in
        (see docs/SETUP/FIELD_TEST_GUIDE.md). On a host, set <code>FIELD_CONSOLE_CORE_URL</code> to sign in through
        SCMTIPS (apps/field-console/README.md).
      </p>
    </div>
  );
}

/** M5-J01: e-mail + password, sent only to this console's server, which signs in at the core and keeps the tokens. */
function CoreSignInForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !email.includes("@")) return setError("Enter your work e-mail address.");
    if (!password) return setError("Enter your password.");
    setBusy(true);
    try {
      const s = await coreSignIn((input, init) => fetch(input, init), email, password, Date.now());
      setPassword("");
      sessionStore.set(s);
      // M5-L03: the sign-in success page offers "Sign in your phone" (contract §8)
      router.push("/phone?signedin=1");
    } catch (err) {
      setError(err instanceof CoreSignInError ? err.message : "Sign-in did not complete.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-2xl font-bold">Sign in</h1>
        <p className="m-0 text-sm text-muted">Use your SCMTIPS account. Your password goes only to SCMTIPS.</p>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="email" className="font-bold">
          E-mail
        </label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="username"
          spellCheck={false}
          className="min-h-[44px] rounded-md border border-control bg-card px-3"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="password" className="font-bold">
          Password
        </label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          className="min-h-[44px] rounded-md border border-control bg-card px-3"
        />
      </div>
      {error ? (
        <p role="alert" className="m-0 rounded-md border border-alert-line bg-alert-bg px-3 py-2 text-alert-ink">
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={busy}
        className="min-h-[48px] rounded-card bg-primary px-4 font-bold text-white hover:bg-primary-hover disabled:opacity-60"
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

function DevSignInForm() {
  const router = useRouter();
  const [role, setRole] = useState<DevRole>("supervisor");
  const [principalId, setPrincipalId] = useState("dev-supervisor");
  const [principalEdited, setPrincipalEdited] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldErrors = touched ? validateSignIn({ role, principalId, tenantId }) : {};

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    setError(null);
    if (Object.keys(validateSignIn({ role, principalId, tenantId })).length) return;
    setBusy(true);
    try {
      const s = await devSignIn(api, { role, principalId, tenantId }, Date.now());
      sessionStore.set(s);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.title : "Sign-in did not complete.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-2xl font-bold">Development sign-in</h1>
        <p className="m-0 rounded-md border-2 border-warn-line bg-warn-bg px-3 py-2 text-sm text-warn-ink">
          For the dev stack on this PC only. The local fake-core service issues the sign-in; no SCMTips account is used.
        </p>
      </div>

      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-1 font-bold">Sign in as</legend>
        {DEV_ROLES.map((r) => (
          <label
            key={r.id}
            className={`flex min-h-[44px] cursor-pointer items-start gap-3 rounded-card border-2 px-3 py-2 ${role === r.id ? "border-primary bg-selected-soft" : "border-line bg-card"}`}
          >
            <input
              type="radio"
              name="role"
              value={r.id}
              checked={role === r.id}
              onChange={() => {
                setRole(r.id);
                if (!principalEdited) setPrincipalId(r.principal);
              }}
              className="mt-1 h-5 w-5 accent-primary"
            />
            <span className="flex flex-col">
              <b>{r.label}</b>
              <span className="text-sm text-muted">{r.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <div className="flex flex-col gap-1">
        <label htmlFor="principal" className="font-bold">
          Your name or id
        </label>
        <input
          id="principal"
          value={principalId}
          onChange={(e) => {
            setPrincipalId(e.target.value);
            setPrincipalEdited(true);
          }}
          autoComplete="username"
          aria-invalid={Boolean(fieldErrors.principalId)}
          aria-describedby={fieldErrors.principalId ? "principal-err" : "principal-hint"}
          className="min-h-[44px] rounded-md border border-control bg-card px-3"
        />
        <span id="principal-hint" className="text-sm text-muted">
          Use a different id from the phone operator, or separation of duties will stop you approving their counts.
        </span>
        {fieldErrors.principalId ? (
          <span id="principal-err" className="text-sm font-bold text-alert-ink">
            {fieldErrors.principalId}
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="tenant" className="font-bold">
          Tenant id
        </label>
        <input
          id="tenant"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          spellCheck={false}
          autoComplete="off"
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          aria-invalid={Boolean(fieldErrors.tenantId)}
          aria-describedby={fieldErrors.tenantId ? "tenant-err tenant-hint" : "tenant-hint"}
          className="min-h-[44px] rounded-md border border-control bg-card px-3 font-mono"
        />
        <span id="tenant-hint" className="text-sm text-muted">
          Open <code>var\dev_stack.json</code> in the SCMTips-Field folder and copy the value of <code>&quot;tenant&quot;</code>.
        </span>
        {fieldErrors.tenantId ? (
          <span id="tenant-err" className="text-sm font-bold text-alert-ink">
            {fieldErrors.tenantId}
          </span>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="m-0 rounded-md border border-alert-line bg-alert-bg px-3 py-2 text-alert-ink">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="min-h-[48px] rounded-card bg-primary px-4 font-bold text-white hover:bg-primary-hover disabled:opacity-60"
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

/** Core sign-in when the server has FIELD_CONSOLE_CORE_URL; the development sign-in when NEXT_PUBLIC_DEV_SIGNIN=1. */
export function LoginView({ coreSignInEnabled }: { coreSignInEnabled: boolean }) {
  return (
    <main className="flex min-h-screen items-start justify-center bg-page p-4 sm:items-center">
      <div className="flex w-full max-w-[460px] flex-col gap-5 rounded-card border border-line bg-card p-6">
        <Brand />
        {coreSignInEnabled ? <CoreSignInForm /> : null}
        {coreSignInEnabled && config.devSignIn ? (
          <details className="rounded-card border border-line p-3">
            <summary className="cursor-pointer font-bold">Development sign-in (this PC only)</summary>
            <div className="mt-3">
              <DevSignInForm />
            </div>
          </details>
        ) : null}
        {!coreSignInEnabled && config.devSignIn ? <DevSignInForm /> : null}
        {!coreSignInEnabled && !config.devSignIn ? <CoreSignInNotBuilt /> : null}
      </div>
    </main>
  );
}
