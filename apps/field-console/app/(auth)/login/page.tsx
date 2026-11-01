/**
 * Login (server part). Which sign-ins are shown is read on the server at request time, so a built image is
 * configured by its runtime environment: FIELD_CONSOLE_CORE_URL set -> sign-in through SCMTIPS (M5-J01);
 * NEXT_PUBLIC_DEV_SIGNIN=1 at build -> the development sign-in; neither -> "not connected yet".
 */
import { LoginView } from "@/components/LoginView";
import { coreSignInConfig } from "@/lib/coreSignIn";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return <LoginView coreSignInEnabled={coreSignInConfig(process.env) !== null} />;
}
