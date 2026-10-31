"""Goods receipts to the SCMTIPS core's ERP feeds (M4 F4; handover 01a, M4 contract section 4).

After erp-sim (the system of record) posts a goods receipt (movement 101), the outbox event ``erp.posted``
(doc_type GoodsReceipt) is turned into two upsert pushes: the stock row(s) to FIELD_CORE_INVENTORY_FEED_URL and the
PO line row(s) to FIELD_CORE_SUPPLY_FEED_URL, each signed with its secret. See publisher.CoreFeedPublisher.
Every FIELD_CORE_SNAPSHOT_INTERVAL_S the ERP's stock and open purchase orders go to the same feeds as a snapshot of
what changed (M4 Q10). See snapshot.ErpSnapshotFeed.
"""

from field_worker.core_feeds.codes import CodeMap, load_code_map
from field_worker.core_feeds.config import FeedConfig
from field_worker.core_feeds.publisher import CoreFeedPublisher
from field_worker.core_feeds.rows import build_rows
from field_worker.core_feeds.signing import sign, signed_headers, verify
from field_worker.core_feeds.snapshot import ErpSnapshotFeed

__all__ = ["CodeMap", "CoreFeedPublisher", "ErpSnapshotFeed", "FeedConfig", "build_rows", "load_code_map", "sign", "signed_headers",
           "verify"]
