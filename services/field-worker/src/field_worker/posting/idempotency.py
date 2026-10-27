"""Posting Idempotency and Pre-Post Document Probing (Task T3.012 / FR3.041 / PR3.06).

Ensures:
1. Every erp_document has exactly one compact 23-char idempotency key: F + base64url(uuid).
2. Before any retry attempt, probes SAP / erp-sim for an existing posted document (by document flow
   or header text matching the idempotency key) and adopts it if found.
"""

import base64
import json
import os
import uuid
from typing import Any

import psycopg

ERPSIM_DATABASE_URL = (
    os.getenv(
        "FIELD_ERPSIM_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


def generate_idempotency_key(base_uuid: uuid.UUID | None = None) -> str:
    """Generate compact 23-character idempotency key: 'F' + base64url(uuid).

    16 bytes of UUID encoded with base64url produces 22 characters (padding stripped).
    Prepending 'F' yields exactly 23 characters.
    """
    raw_bytes = (base_uuid or uuid.uuid4()).bytes
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")
    return f"F{encoded}"


def probe_sap_document(
    sap_client: str = "100",
    doc_family: str = "GoodsReceipt",
    ref_doc_no: str | None = None,
    idempotency_key: str | None = None,
    cur: psycopg.Cursor[Any] | None = None,
    erpsim_db_url: str = ERPSIM_DATABASE_URL,
) -> dict[str, Any] | None:
    """Probe ERP / erp-sim for an existing posted document before retrying.

    Checks erpsim.dedupe or document flow in erpsim.document to see if
    a document was already committed under this idempotency key or ref_doc_no.
    """
    if cur is not None:
        return _probe_with_cursor(cur, sap_client, doc_family, ref_doc_no, idempotency_key)

    try:
        with psycopg.connect(erpsim_db_url, autocommit=True) as conn, conn.cursor() as erp_cur:
            return _probe_with_cursor(erp_cur, sap_client, doc_family, ref_doc_no, idempotency_key)
    except Exception:
        return None


def _probe_with_cursor(
    cur: psycopg.Cursor[Any],
    sap_client: str,
    doc_family: str,
    ref_doc_no: str | None,
    idempotency_key: str | None,
) -> dict[str, Any] | None:
    # 1. Probe by idempotency key in sim dedupe table
    if idempotency_key:
        cur.execute(
            """
            SELECT document_no, fiscal_year
            FROM erpsim.dedupe
            WHERE client = %s AND idem_key = %s;
        """,
            (sap_client, idempotency_key),
        )
        row = cur.fetchone()
        if row:
            return {
                "document_number": row[0],
                "fiscal_year": row[1],
                "adopted_by_probe": True,
            }

    # 2. Probe by ref_doc_no in document header_data
    if ref_doc_no:
        cur.execute(
            """
            SELECT doc_number, fiscal_year, header_data
            FROM erpsim.document
            WHERE client = %s AND status = 'posted'
            ORDER BY created_at DESC
            LIMIT 10;
        """,
            (sap_client,),
        )
        for d_num, d_yr, h_data in cur.fetchall():
            data_dict = h_data if isinstance(h_data, dict) else json.loads(h_data or "{}")
            if (
                data_dict.get("DeliveryDocument") == ref_doc_no
                or data_dict.get("PhysicalInventoryDocument") == ref_doc_no
                or data_dict.get("RefDoc") == ref_doc_no
                or (idempotency_key and data_dict.get("IdempotencyKey") == idempotency_key)
            ):
                return {
                    "document_number": d_num,
                    "fiscal_year": d_yr,
                    "adopted_by_probe": True,
                }

    return None
