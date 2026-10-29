"""Enhance Installed Base View for API4.18 (Task T4.027 / FR4.065 / API4.18).

Revision ID: field_0051
Revises: field_0050
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0051"
down_revision = "field_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS field.installed_base CASCADE;

        CREATE VIEW field.installed_base WITH (security_invoker = true) AS
        SELECT
            e.tenant_id,
            e.serial_no,
            e.id AS equipment_id,
            e.erp_equipment_no,
            e.material,
            e.equipment_class,
            e.pinned_model_version,
            s.id AS site_id,
            s.code AS site_erp_ref,
            s.name AS site_name,
            l.id AS location_id,
            l.sector_code,
            l.height_m AS level_height_m,
            l.code AS position_code,
            l.fl_code AS erp_ref,
            COALESCE(se.occurred_at, e.created_at) AS since
        FROM field.equipment e
        LEFT JOIN field.location l ON e.current_location_id = l.id
        LEFT JOIN field.site s ON l.site_id = s.id
        LEFT JOIN LATERAL (
            SELECT occurred_at FROM field.serial_event se_sub
            WHERE se_sub.tenant_id = e.tenant_id AND se_sub.equipment_id = e.id AND se_sub.type IN ('install', 'move', 'audit_seen')
            ORDER BY se_sub.seq DESC LIMIT 1
        ) se ON true
        WHERE e.status = 'installed';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS field.installed_base CASCADE;

        CREATE VIEW field.installed_base WITH (security_invoker = true) AS
        SELECT
            e.tenant_id,
            e.serial_no,
            e.id AS equipment_id,
            e.erp_equipment_no,
            e.material,
            l.site_id,
            l.id AS location_id,
            l.sector_code,
            l.height_m AS level_height_m,
            l.fl_code AS erp_ref,
            COALESCE(se.occurred_at, e.created_at) AS since
        FROM field.equipment e
        LEFT JOIN field.location l ON e.current_location_id = l.id
        LEFT JOIN LATERAL (
            SELECT occurred_at FROM field.serial_event s
            WHERE s.tenant_id = e.tenant_id AND s.equipment_id = e.id AND s.type IN ('install', 'move', 'audit_seen')
            ORDER BY s.seq DESC LIMIT 1
        ) se ON true
        WHERE e.status = 'installed';
        """
    )
