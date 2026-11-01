# SCMTIPS Field operations image for the hosted VM-1 (first-run seeding and smokes; never a long-running service).
# Build context: the hosting kit's source tarball, which holds the SCMTIPS core and this repository side by side as
# core/ and field/ (scmtips-hosting build.sh):
#   docker build -f field/deploy/hosted/ops.Dockerfile -t scmtips-field-ops .
# It is the field-api runtime plus tools/dev_stack and the core's SAMPLE exports and scenario pack (read only), so
# on the VM:
#   docker compose run --rm field-ops python -m tools.dev_stack.stack seed-core-export /samples/exports/erp-sim
#   docker compose run --rm field-ops python -m tools.dev_stack.stack smoke --core
# reach erp-sim's database and field-api over the kit's internal network (FIELD_STACK_*_URL, deploy/hosted).

ARG FIELD_API_IMAGE=scmtips-field-api:local
FROM ${FIELD_API_IMAGE}
USER root
COPY field/tools/dev_stack /app/tools/dev_stack
COPY core/samples/exports /samples/exports
COPY core/samples/scenarios /samples/scenarios
RUN mkdir -p /app/var && chown -R 10001:10001 /app/var /app/tools
USER 10001:10001
WORKDIR /app
HEALTHCHECK NONE
CMD ["python", "-m", "tools.dev_stack.stack", "--help"]
