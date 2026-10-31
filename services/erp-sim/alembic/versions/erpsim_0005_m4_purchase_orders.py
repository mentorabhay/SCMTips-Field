"""M4 Q10: purchase orders in the simulator, so the field can send the core a snapshot of the open POs.

- erpsim.purchase_order(client, purchase_order, supplier, created_at): the PO header (S/4 A_PurchaseOrder).
- erpsim.purchase_order_item(client, purchase_order, item_no, material_no, plant, storage_location, order_qty, uom,
  delivery_date, status, ext): one PO line (S/4 A_PurchaseOrderItem with its schedule line's delivery date).
  ``status`` is the supply status the core knows the line by (open, released, in_transit), kept as the core's export
  gives it; ``ext`` holds pass-through planning attributes of the export (``lane_code``). Neither exists in S/4:
  served as YY1_ fields by API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrderItem (simulator only).

What has been received is not stored: it is the sum of the goods receipts (101) whose items reference the PO line
(erpsim.document_item.item_data PurchaseOrder / PurchaseOrderItem, erpsim_0004), less reversed documents and
cancelled items, so the open quantity follows every posting and reversal.

Revision ID: erpsim_0005
Revises: erpsim_0004
"""

from alembic import op

revision = "erpsim_0005"
down_revision = "erpsim_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE erpsim.purchase_order (
            client text NOT NULL DEFAULT '100',
            purchase_order text NOT NULL,
            supplier text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, purchase_order)
        );
        CREATE TABLE erpsim.purchase_order_item (
            client text NOT NULL DEFAULT '100',
            purchase_order text NOT NULL,
            item_no text NOT NULL,
            material_no text NOT NULL,
            plant text NOT NULL,
            storage_location text NOT NULL DEFAULT '',
            order_qty numeric(12,3) NOT NULL CHECK (order_qty > 0),
            uom text NOT NULL DEFAULT 'EA',
            delivery_date date NULL,
            status text NOT NULL DEFAULT 'open',
            ext jsonb NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (client, purchase_order, item_no),
            CONSTRAINT fk_po_item_po FOREIGN KEY (client, purchase_order)
                REFERENCES erpsim.purchase_order (client, purchase_order) ON DELETE CASCADE
        );
        CREATE INDEX idx_po_item_plant ON erpsim.purchase_order_item (client, plant);
        CREATE INDEX idx_document_item_po ON erpsim.document_item (client, (item_data->>'PurchaseOrder'))
            WHERE item_data ? 'PurchaseOrder';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS erpsim.idx_document_item_po;
        DROP TABLE IF EXISTS erpsim.purchase_order_item;
        DROP TABLE IF EXISTS erpsim.purchase_order;
        """
    )
