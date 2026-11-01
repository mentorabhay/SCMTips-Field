/** POST /api/console-auth/signin. E-mail + password -> SCMTIPS core app token -> field token, kept in httpOnly cookies (M5-J01). */
import type { NextRequest } from "next/server";
import { handleSignIn } from "../../../../lib/consoleAuthHandlers";
import { serverDeps } from "../../../../lib/consoleAuthDeps";

export const dynamic = "force-dynamic";

export function POST(req: NextRequest) {
  return handleSignIn(req, serverDeps());
}
