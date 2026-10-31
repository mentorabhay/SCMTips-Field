"""M4 F4: purchase-order references on inbound delivery items, carried into the goods receipt.

- erpsim.inbound_delivery_item.purchase_order / purchase_order_item: the PO line an inbound delivery item
  (an ASN) was created for, as S/4's A_InbDeliveryItem.ReferenceSDDocument / ReferenceSDDocumentItem.
  NULL for deliveries without a PO (SAMPLE deliveries, sandbox receipts).
- The goods receipt (101) copies them into erpsim.document_item.item_data, and the material document is read
  with them as A_MaterialDocumentItem.PurchaseOrder / PurchaseOrderItem (what S/4 serves for a GR to a PO).
  The field's goods-receipt feed to the core (M4 contract section 4, F4) builds its PO row from them.

Revision ID: erpsim_0004
Revises: erpsim_0003
"""

from alembic import op

revision = "erpsim_0004"
down_revision = "erpsim_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE erpsim.inbound_delivery_item ADD COLUMN IF NOT EXISTS purchase_order text NULL;
        ALTER TABLE erpsim.inbound_delivery_item ADD COLUMN IF NOT EXISTS purchase_order_item text NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE erpsim.inbound_delivery_item DROP COLUMN IF EXISTS purchase_order_item;
        ALTER TABLE erpsim.inbound_delivery_item DROP COLUMN IF EXISTS purchase_order;
        """
    )
