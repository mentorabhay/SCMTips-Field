"""CLI for SCMTIPS Field Admin operations (Task T1.030 / CS-02 bootstrap)."""

import argparse
import json
import os
import sys
import uuid

import psycopg
from field_common.uuid7 import uuid7_str


def get_db_url() -> str:
    return os.getenv(
        "FIELD_ADMIN_DATABASE_URL",
        os.getenv(
            "FIELD_DATABASE_URL",
            "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
        ),
    ).replace("postgresql+psycopg://", "postgresql://")


def cmd_grant(args: argparse.Namespace) -> int:
    tenant_id = args.tenant
    user_id = args.user
    role = args.role
    site_ids = args.site_ids.split(",") if args.site_ids else ["*"]
    granted_by = args.granted_by or "bootstrap-cli"

    # Validate tenant UUID
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        print(f"Error: Invalid tenant UUID: {tenant_id}", file=sys.stderr)
        return 1

    valid_roles = {
        "field.operator",
        "field.technician",
        "field.supervisor",
        "inventory.controller",
        "field.integration",
        "field.viewer",
        "field.admin",
    }
    if role not in valid_roles:
        print(f"Error: Invalid role {role}. Allowed: {sorted(valid_roles)}", file=sys.stderr)
        return 1

    grant_id = uuid7_str()
    outbox_id = uuid7_str()

    try:
        with psycopg.connect(get_db_url(), autocommit=False) as conn:
            with conn.cursor() as cur:
                # Set tenant context
                cur.execute(f"SET app.tenant_id = '{tenant_id}';")

                # Upsert into field.role_grant
                cur.execute(
                    """
                    INSERT INTO field.role_grant (id, tenant_id, principal_id, role, site_ids, granted_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, principal_id, role)
                    DO UPDATE SET site_ids = EXCLUDED.site_ids, granted_by = EXCLUDED.granted_by
                    RETURNING id;
                """,
                    (grant_id, tenant_id, user_id, role, site_ids, granted_by),
                )
                actual_id = cur.fetchone()[0]

                # Audit record in field.outbox
                outbox_payload = {
                    "grant_id": str(actual_id),
                    "tenant_id": tenant_id,
                    "principal_id": user_id,
                    "role": role,
                    "site_ids": site_ids,
                    "granted_by": granted_by,
                }
                cur.execute(
                    """
                    INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                    VALUES (%s, %s, %s, 'role_grant.created', %s);
                """,
                    (outbox_id, tenant_id, str(actual_id), json.dumps(outbox_payload)),
                )

            conn.commit()
            print(f"Role grant successfully created/updated: {actual_id}")
            print(f"Audited to field.outbox: {outbox_id}")
            return 0
    except Exception as e:
        print(f"Failed to execute role grant: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="field-api", description="SCMTIPS Field API Admin CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    grant_parser = subparsers.add_parser("grant", help="Grant a role to a principal")
    grant_parser.add_argument("--tenant", required=True, help="Tenant UUID")
    grant_parser.add_argument("--user", required=True, help="User/Principal ID")
    grant_parser.add_argument("--role", required=True, help="Role name (e.g. field.admin)")
    grant_parser.add_argument("--site-ids", default="*", help="Comma-separated site IDs or *")
    grant_parser.add_argument("--granted-by", default="bootstrap-cli", help="Granter identity")

    args = parser.parse_args()
    if args.command == "grant":
        return cmd_grant(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
