"""M5-S01 two-step look: the first answer as soon as SAM's instances are counted, the label read after it.

field.vision_look gains:
- ``final`` (boolean, default true: every look written before this migration was final): false while the label read
  of the look is still running after the first answer (source ``partial``, counts.seen set, no labels yet);
- ``say_next`` (text): what the app speaks once the look is final, after the first answer it already spoke (the
  final ``say`` without the count sentence it repeats); null on a look that was final in one step;
- ``labels_due_at`` (timestamptz): when an unfinished label read is given up: any read after it ends the look
  (``final`` true, source ``partial``, reason ``labels:not_finished``), so a field-api restart in the middle of a read
  never leaves a look waiting for ever;
- ``labels_fallback`` (jsonb): the counts, pack, expiry and proposal of the look with every label unread, written with
  the first answer and used when the label read fails, times out or is given up.

No new table: the forced RLS policies of field_0064_m5_vision apply unchanged.

Revision ID: field_0066_m5_look_stage
Revises: field_0065
"""

from alembic import op

revision = "field_0066_m5_look_stage"
down_revision = "field_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.vision_look
            ADD COLUMN final boolean NOT NULL DEFAULT true,
            ADD COLUMN say_next text,
            ADD COLUMN labels_due_at timestamptz,
            ADD COLUMN labels_fallback jsonb,
            ADD CONSTRAINT ck_vision_look_pending CHECK (final OR (labels_due_at IS NOT NULL
                                                                   AND labels_fallback IS NOT NULL));
        CREATE INDEX idx_vision_look_pending ON field.vision_look (labels_due_at) WHERE NOT final;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS field.idx_vision_look_pending;
        ALTER TABLE field.vision_look
            DROP CONSTRAINT IF EXISTS ck_vision_look_pending,
            DROP COLUMN IF EXISTS labels_fallback,
            DROP COLUMN IF EXISTS labels_due_at,
            DROP COLUMN IF EXISTS say_next,
            DROP COLUMN IF EXISTS final;
        """
    )
