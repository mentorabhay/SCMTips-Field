# SCMTIPS Field console image (hud.scmtips.com on VM-1). Build from the repository root:
#   docker build -f deploy/docker/console.Dockerfile -t scmtips-field-console .
# The console has dynamic routes (sites/[id]/towers, models/[id]) and same-origin /v1 rewrites to field-api, so it
# runs as a minimal Next.js standalone server rather than a static export. The rewrite target is fixed at build
# time (FIELD_API_INTERNAL_URL, default http://field-api:8020, the kit's internal field-api); the browser only ever
# calls this host. The development sign-in (NEXT_PUBLIC_DEV_SIGNIN) is off in this image. Sign-in through the SCMTIPS
# core (M5-J01) is configured at RUN time: set FIELD_CONSOLE_CORE_URL (e.g. http://api:8000) on the console container
# (see deploy/hosted/field.env.example and apps/field-console/README.md); without it the login page says core sign-in
# is not connected. Runs as the non-root `node` user.

ARG NODE_IMAGE=node:22.23.4-slim
# The pnpm that wrote pnpm-lock.yaml (the repository pins no packageManager; a newer pnpm refuses ignored builds).
ARG PNPM_VERSION=10.28.0

FROM ${NODE_IMAGE} AS build
ARG PNPM_VERSION
ENV NEXT_TELEMETRY_DISABLED=1 \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable && corepack prepare "pnpm@${PNPM_VERSION}" --activate
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/field-console ./apps/field-console
RUN pnpm install --frozen-lockfile --filter @scmtips-field/field-console...
ARG FIELD_API_INTERNAL_URL=http://field-api:8020
ENV NEXT_PUBLIC_FIELD_API_URL=${FIELD_API_INTERNAL_URL} \
    NEXT_PUBLIC_DEV_SIGNIN=0 \
    NEXT_OUTPUT=standalone
RUN pnpm --filter @scmtips-field/field-console build

FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /repo/apps/field-console/.next/standalone ./
COPY --from=build --chown=node:node /repo/apps/field-console/.next/static ./apps/field-console/.next/static
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.status<500?0:1),()=>process.exit(1))"]
CMD ["node", "apps/field-console/server.js"]
