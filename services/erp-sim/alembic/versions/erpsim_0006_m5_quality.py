"""M5: flagged units of an inbound delivery item post 101 to a quality storage location (docs/design/M5_CONTRACT.md §2).

- erpsim.inbound_delivery_item.quality_qty: the part of the item's actual quantity that the goods receipt posts to
  ``quality_sloc`` instead of the delivery's storage location (0 = none, the pre-M5 receipt).
- erpsim.inbound_delivery_item.quality_sloc: that storage location (e.g. 101Q, "Quality Inspection Holding"); it must
  exist in the delivery's plant.

Set through PATCH A_InbDeliveryItem with YY1_QualityQuantity / YY1_QualityStorageLocation, extension fields of the
simulator only (a real S/4 system would split the item or use the quality inspection stock type: UNVERIFIED).

Revision ID: erpsim_0006
Revises: erpsim_0005
"""

from alembic import op

revision = "erpsim_0006"
down_revision = "erpsim_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE erpsim.inbound_delivery_item ADD COLUMN IF NOT EXISTS quality_qty numeric(12,3) NOT NULL DEFAULT 0
            CHECK (quality_qty >= 0);
        ALTER TABLE erpsim.inbound_delivery_item ADD COLUMN IF NOT EXISTS quality_sloc text NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE erpsim.inbound_delivery_item DROP COLUMN IF EXISTS quality_sloc;
        ALTER TABLE erpsim.inbound_delivery_item DROP COLUMN IF EXISTS quality_qty;
        """
    )
