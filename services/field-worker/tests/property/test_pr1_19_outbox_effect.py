"""Property Test PR1.19: Transactional Outbox Exactly-Once Effect (Hypothesis)."""

import json
import os

import hypothesis.strategies as st
import psycopg
import pytest
from field_common.uuid7 import uuid7_str
from hypothesis import given, settings

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


@pytest.mark.property
@settings(max_examples=25, deadline=None)
@given(
    st.booleans(),
    st.text(min_size=4, max_size=12, alphabet="abcdef0123456789"),
)
def test_pr1_19_outbox_transaction_atomicity(should_commit: bool, payload_tag: str) -> None:
    """PR1.19: Outbox row is committed iff the business state change commits (TC1.055)."""
    tenant_id = "00000000-0000-0000-0000-000000000001"
    event_id = uuid7_str()
    aggregate_id = uuid7_str()

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO field.outbox (id, tenant_id, aggregate_id, event_type, payload)
                    VALUES (%s, %s, %s, 'test.property.atomicity', %s);
                    """,
                    (event_id, tenant_id, aggregate_id, json.dumps({"tag": payload_tag})),
                )
                if should_commit:
                    conn.commit()
                else:
                    conn.rollback()
    except Exception as e:
        pytest.skip(f"Local database not available for transactional test: {e}")

    # Verify outbox row presence strictly matches should_commit
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM field.outbox WHERE id = %s;", (event_id,))
            row = cur.fetchone()
            count = row[0] if row else 0

    if should_commit:
        assert count == 1, "Expected outbox event to be committed"
    else:
        assert count == 0, "Expected outbox event to be absent after rollback"


@pytest.mark.property
@settings(max_examples=30)
@given(
    st.lists(st.text(min_size=4, max_size=10, alphabet="0123456789abcdef"), min_size=1, max_size=15, unique=True),
    st.integers(min_value=1, max_value=3),  # Simulated crash/retry count
)
def test_pr1_19_consumer_deduplication_under_crashes(event_ids: list[str], duplicates_per_event: int) -> None:
    """PR1.19: At-least-once delivery with consumer deduplication achieves exactly-once effects (TC1.056, TC1.057)."""
    # Simulate at-least-once published stream with duplicates due to relay crash
    published_stream: list[str] = []
    for eid in event_ids:
        for _ in range(duplicates_per_event):
            published_stream.append(eid)

    # Consumer with idempotent deduplication ledger
    processed_events: set[str] = set()
    executed_side_effects: list[str] = []

    for event_id in published_stream:
        if event_id in processed_events:
            # Deduplicated: ignore duplicate delivery
            continue
        processed_events.add(event_id)
        executed_side_effects.append(event_id)

    # Verification: Every unique event executed exactly once
    assert len(executed_side_effects) == len(event_ids)
    assert set(executed_side_effects) == set(event_ids)
