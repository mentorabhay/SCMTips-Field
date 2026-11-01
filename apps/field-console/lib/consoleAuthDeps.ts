/** The real dependencies of the sign-in route handlers: the server's fetch, its environment at request time, its clock. */
import type { HandlerDeps } from "./consoleAuthHandlers";

export function serverDeps(): HandlerDeps {
  return {
    fetch: (input, init) => fetch(input, init),
    env: process.env,
    nowS: () => Math.floor(Date.now() / 1000),
    newId: () => crypto.randomUUID(),
  };
}
