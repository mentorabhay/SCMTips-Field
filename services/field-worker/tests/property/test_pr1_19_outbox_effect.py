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
        "FIELD_ADMIN_DATABASE_URL",
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

    # No skip: a missing database is a failure (rule 2.1). Note: this exercises Postgres transaction
    # semantics for the outbox table only; the production "state change + outbox in one tx" path
    # is not covered here (PR1.19 stays partial).
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


# test_pr1_19_consumer_deduplication_under_crashes removed (C2): it simulated a consumer in the test
# itself and called no production code. No outbox relay/consumer exists yet (T1.023 partial), so PR1.19's
# exactly-once clause is unproven.
