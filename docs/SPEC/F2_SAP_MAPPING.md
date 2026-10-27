# Phase 3 SAP OData Declarative Mappings Ledger (Task T3.006 / FR3.042)

**Specification Requirement**: `FR3.042` — The system shall keep field-level mappings in versioned declarative files per OData service with a `VERIFIED`/`UNVERIFIED` status per row.  
**Test Reference**: `TC3.134` (Contract: Mapping files and golden payloads)  
**Property Invariant**: `PR3.15` (Sim parity)  

---

## 1. Mappings Overview

| Service Name | Declarative File | Version | Entities Mapped | Function Imports | Status |
| :--- | :--- | :---: | :--- | :--- | :---: |
| `API_INBOUND_DELIVERY_SRV` | `connectors/sap/mappings/inbound_delivery.yaml` | 2.0 | `A_InbDeliveryHeader`, `A_InbDeliveryItem` | `PostGoodsReceipt`, `PutawayItem` | **VERIFIED** |
| `API_OUTBOUND_DELIVERY_SRV` | `connectors/sap/mappings/outbound_delivery.yaml` | 2.0 | `A_OutbDeliveryHeader`, `A_OutbDeliveryItem` | `PickOneItem`, `ConfirmPickingOneItem`, `PostGoodsIssue`, `ReverseGoodsIssue` | **VERIFIED** |
| `API_PHYSICAL_INVENTORY_DOC_SRV` | `connectors/sap/mappings/physinv.yaml` | 2.0 | `A_PhysInventoryDocHeader`, `A_PhysInventoryDocItem` | `InitiateRecount`, `PostDifferences` | **VERIFIED** |
| `API_MATERIAL_DOCUMENT_SRV` | `connectors/sap/mappings/material_document.yaml` | 2.0 | `A_MaterialDocumentHeader`, `A_MaterialDocumentItem` | `Cancel`, `CancelItem` | **VERIFIED** |

---

## 2. Inbound Delivery (`API_INBOUND_DELIVERY_SRV`)

### Entities
| Entity | Local Field | SAP OData Property | Edm Type | Verification Status | Notes |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `A_InbDeliveryHeader` | `delivery_document` | `DeliveryDocument` | `Edm.String(10)` | **VERIFIED** | Key field |
| `A_InbDeliveryHeader` | `receiving_plant` | `ReceivingPlant` | `Edm.String(4)` | **VERIFIED** | |
| `A_InbDeliveryHeader` | `storage_location` | `StorageLocation` | `Edm.String(4)` | **VERIFIED** | |
| `A_InbDeliveryHeader` | `goods_movement_status` | `OverallGoodsMovementStatus` | `Edm.String(1)` | **VERIFIED** | 'C' on receipt |
| `A_InbDeliveryHeader` | `goods_receipt_status` | `OverallGoodsReceiptStatus` | `Edm.String(1)` | **VERIFIED** | |
| `A_InbDeliveryItem` | `delivery_document` | `DeliveryDocument` | `Edm.String(10)` | **VERIFIED** | Composite Key |
| `A_InbDeliveryItem` | `item_no` | `DeliveryDocumentItem` | `Edm.String(6)` | **VERIFIED** | Composite Key |
| `A_InbDeliveryItem` | `material_no` | `Material` | `Edm.String(40)` | **VERIFIED** | |
| `A_InbDeliveryItem` | `delivery_qty` | `ActualDeliveryQuantity` | `Edm.Decimal(13,3)`| **VERIFIED** | PATCH target |
| `A_InbDeliveryItem` | `movement_qty` | `ActualGoodsMovementQty` | `Edm.Decimal(13,3)`| **VERIFIED** | |
| `A_InbDeliveryItem` | `uom` | `DeliveryQuantityUnit` | `Edm.String(3)` | **VERIFIED** | |
| `A_InbDeliveryItem` | `storage_bin` | `StorageBin` | `Edm.String(10)` | *UNVERIFIED* | Optional putaway |

### Function Imports
| Name | Method | Parameters | Return Type | Status |
| :--- | :---: | :--- | :--- | :---: |
| `PostGoodsReceipt` | `POST` | `DeliveryDocument` (`Edm.String`) | `A_InbDeliveryHeader` | **VERIFIED** |
| `PutawayItem` | `POST` | `DeliveryDocument`, `DeliveryDocumentItem`, `StorageBin` | `A_InbDeliveryItem` | **VERIFIED** |

---

## 3. Outbound Delivery (`API_OUTBOUND_DELIVERY_SRV`)

### Entities
| Entity | Local Field | SAP OData Property | Edm Type | Verification Status | Notes |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `A_OutbDeliveryHeader`| `delivery_document` | `DeliveryDocument` | `Edm.String(10)` | **VERIFIED** | Key field |
| `A_OutbDeliveryHeader`| `shipping_plant` | `ShippingPlant` | `Edm.String(4)` | **VERIFIED** | |
| `A_OutbDeliveryHeader`| `storage_location` | `StorageLocation` | `Edm.String(4)` | **VERIFIED** | |
| `A_OutbDeliveryHeader`| `goods_issue_status` | `OverallGoodsIssueStatus` | `Edm.String(1)` | **VERIFIED** | 'C' on issue |
| `A_OutbDeliveryItem` | `delivery_document` | `DeliveryDocument` | `Edm.String(10)` | **VERIFIED** | Composite Key |
| `A_OutbDeliveryItem` | `item_no` | `DeliveryDocumentItem` | `Edm.String(6)` | **VERIFIED** | Composite Key |
| `A_OutbDeliveryItem` | `material_no` | `Material` | `Edm.String(40)` | **VERIFIED** | |
| `A_OutbDeliveryItem` | `delivery_qty` | `ActualDeliveryQuantity` | `Edm.Decimal(13,3)`| **VERIFIED** | Target quantity |
| `A_OutbDeliveryItem` | `picked_qty` | `PickedQuantity` | `Edm.Decimal(13,3)`| **VERIFIED** | PATCH target |
| `A_OutbDeliveryItem` | `uom` | `DeliveryQuantityUnit` | `Edm.String(3)` | **VERIFIED** | |
| `A_OutbDeliveryItem` | `storage_bin` | `StorageBin` | `Edm.String(10)` | *UNVERIFIED* | |

### Function Imports
| Name | Method | Parameters | Return Type | Status |
| :--- | :---: | :--- | :--- | :---: |
| `PickOneItem` | `POST` | `DeliveryDocument`, `DeliveryDocumentItem`, `PickedQuantity` | `A_OutbDeliveryItem` | **VERIFIED** |
| `ConfirmPickingOneItem`| `POST` | `DeliveryDocument`, `DeliveryDocumentItem` | `A_OutbDeliveryItem` | **VERIFIED** |
| `PostGoodsIssue` | `POST` | `DeliveryDocument`, `AllowPartial` | `A_OutbDeliveryHeader` | **VERIFIED** |
| `ReverseGoodsIssue` | `POST` | `DeliveryDocument` | `A_OutbDeliveryHeader` | **VERIFIED** |

---

## 4. Physical Inventory (`API_PHYSICAL_INVENTORY_DOC_SRV`)

### Entities
| Entity | Local Field | SAP OData Property | Edm Type | Verification Status | Notes |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `A_PhysInventoryDocHeader` | `pi_document` | `PhysicalInventoryDocument` | `Edm.String(10)` | **VERIFIED** | Composite Key |
| `A_PhysInventoryDocHeader` | `fiscal_year` | `FiscalYear` | `Edm.String(4)` | **VERIFIED** | Composite Key |
| `A_PhysInventoryDocHeader` | `plant` | `Plant` | `Edm.String(4)` | **VERIFIED** | |
| `A_PhysInventoryDocHeader` | `storage_location` | `StorageLocation` | `Edm.String(4)` | **VERIFIED** | |
| `A_PhysInventoryDocHeader` | `posting_blocked` | `PostingBlocked` | `Edm.Boolean` | **VERIFIED** | Freeze flag |
| `A_PhysInventoryDocHeader` | `freeze_book` | `FreezeBookInventory` | `Edm.Boolean` | **VERIFIED** | Freeze flag |
| `A_PhysInventoryDocHeader` | `status` | `Status` | `Edm.String(10)` | **VERIFIED** | |
| `A_PhysInventoryDocItem` | `pi_document` | `PhysicalInventoryDocument` | `Edm.String(10)` | **VERIFIED** | Composite Key |
| `A_PhysInventoryDocItem` | `fiscal_year` | `FiscalYear` | `Edm.String(4)` | **VERIFIED** | Composite Key |
| `A_PhysInventoryDocItem` | `item_no` | `PhysicalInventoryDocumentItem`| `Edm.String(3)` | **VERIFIED** | Composite Key |
| `A_PhysInventoryDocItem` | `material_no` | `Material` | `Edm.String(40)` | **VERIFIED** | |
| `A_PhysInventoryDocItem` | `book_qty` | `BookQuantity` | `Edm.Decimal(13,3)`| **VERIFIED** | Frozen baseline |
| `A_PhysInventoryDocItem` | `counted_qty` | `QuantityInEntryUnit` | `Edm.Decimal(13,3)`| **VERIFIED** | Blind count entry |
| `A_PhysInventoryDocItem` | `uom` | `EntryUnit` | `Edm.String(3)` | **VERIFIED** | |

### Function Imports
| Name | Method | Parameters | Return Type | Status |
| :--- | :---: | :--- | :--- | :---: |
| `InitiateRecount` | `POST` | `PhysicalInventoryDocument`, `FiscalYear` | `A_PhysInventoryDocHeader` | **VERIFIED** |
| `PostDifferences` | `POST` | `PhysicalInventoryDocument`, `FiscalYear` | `A_PhysInventoryDocHeader` | **VERIFIED** |

---

## 5. Material Document (`API_MATERIAL_DOCUMENT_SRV`)

### Entities
| Entity | Local Field | SAP OData Property | Edm Type | Verification Status | Notes |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `A_MaterialDocumentHeader` | `doc_number` | `MaterialDocument` | `Edm.String(10)` | **VERIFIED** | Composite Key |
| `A_MaterialDocumentHeader` | `fiscal_year` | `MaterialDocumentYear` | `Edm.String(4)` | **VERIFIED** | Composite Key |
| `A_MaterialDocumentHeader` | `document_date` | `DocumentDate` | `Edm.DateTime` | **VERIFIED** | |
| `A_MaterialDocumentHeader` | `posting_date` | `PostingDate` | `Edm.DateTime` | **VERIFIED** | |
| `A_MaterialDocumentHeader` | `movement_code` | `GoodsMovementCode` | `Edm.String(2)` | **VERIFIED** | '01' |
| `A_MaterialDocumentItem` | `doc_number` | `MaterialDocument` | `Edm.String(10)` | **VERIFIED** | Composite Key |
| `A_MaterialDocumentItem` | `fiscal_year` | `MaterialDocumentYear` | `Edm.String(4)` | **VERIFIED** | Composite Key |
| `A_MaterialDocumentItem` | `line_no` | `MaterialDocumentItem` | `Edm.String(4)` | **VERIFIED** | Line counter |
| `A_MaterialDocumentItem` | `material_no` | `Material` | `Edm.String(40)` | **VERIFIED** | |
| `A_MaterialDocumentItem` | `plant` | `Plant` | `Edm.String(4)` | **VERIFIED** | |
| `A_MaterialDocumentItem` | `storage_location` | `StorageLocation` | `Edm.String(4)` | **VERIFIED** | |
| `A_MaterialDocumentItem` | `movement_type` | `GoodsMovementType` | `Edm.String(3)` | **VERIFIED** | 101, 102, 601, 602, 701, 702 |
| `A_MaterialDocumentItem` | `quantity` | `QuantityInEntryUnit` | `Edm.Decimal(13,3)`| **VERIFIED** | |
| `A_MaterialDocumentItem` | `uom` | `EntryUnit` | `Edm.String(3)` | **VERIFIED** | |

### Function Imports
| Name | Method | Parameters | Return Type | Status |
| :--- | :---: | :--- | :--- | :---: |
| `Cancel` | `POST` | `MaterialDocument`, `MaterialDocumentYear` | `A_MaterialDocumentHeader` | **VERIFIED** |
| `CancelItem` | `POST` | `MaterialDocument`, `MaterialDocumentYear`, `MaterialDocumentItem` | `A_MaterialDocumentItem` | **VERIFIED** |
