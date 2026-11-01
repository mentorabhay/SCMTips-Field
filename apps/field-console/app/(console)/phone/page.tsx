/**
 * "Sign in your phone" (M5-L03, server part). Whether the console signs in through SCMTIPS is read on the server at
 * request time (FIELD_CONSOLE_CORE_URL), as on the login page; `?signedin=1` is the sign-in success page.
 */
import { PhonePairingView } from "@/components/PhonePairingView";
import { coreSignInConfig } from "@/lib/coreSignIn";

export const dynamic = "force-dynamic";

export default async function PhonePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  return <PhonePairingView coreSignInEnabled={coreSignInConfig(process.env) !== null} justSignedIn={sp.signedin === "1"} />;
}
