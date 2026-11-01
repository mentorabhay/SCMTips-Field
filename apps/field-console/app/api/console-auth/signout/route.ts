/** POST /api/console-auth/signout. Sign out: clears the console's token cookies (M5-J01). */
import type { NextRequest } from "next/server";
import { handleSignOut } from "../../../../lib/consoleAuthHandlers";
import { serverDeps } from "../../../../lib/consoleAuthDeps";

export const dynamic = "force-dynamic";

export function POST(req: NextRequest) {
  return handleSignOut(req, serverDeps());
}
