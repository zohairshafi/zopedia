"""Pending trade-approval queue.

These are the properties that keep the queue from ever placing an order twice or
placing an expired one, so they are tested directly rather than inferred from
the UI behaving correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import periodic_store  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the store at a throwaway DB so tests never touch real data."""
    monkeypatch.setattr(periodic_store, "_DB_PATH", str(tmp_path / "periodic.db"))
    return periodic_store


ORDER = {
    "asset_type": "equity",
    "symbol": "AAPL",
    "side": "buy",
    "qty": 1,
    "type": "market",
    "time_in_force": "day",
    "client_order_id": "",
    "rationale": "test",
}


def test_created_approval_is_listed_with_its_order(store):
    approval_id = store.create_pending_approval(
        "zohair", ORDER, rationale="because", config_id="cfg1", thread_id="th1"
    )
    pending = store.list_pending_approvals("zohair")
    assert [a["id"] for a in pending] == [approval_id]
    assert pending[0]["order"]["symbol"] == "AAPL"
    assert pending[0]["rationale"] == "because"
    assert pending[0]["status"] == "pending"


def test_claim_succeeds_once_then_refuses(store):
    """The double-approve guard: two clicks must produce exactly one placement."""
    approval_id = store.create_pending_approval("zohair", ORDER)

    first = store.claim_pending_approval(approval_id, "zohair")
    assert first is not None and first["status"] == "approved"

    second = store.claim_pending_approval(approval_id, "zohair")
    assert second is None, "a second claim must not hand out a second placement"


def test_expired_approval_cannot_be_claimed(store):
    approval_id = store.create_pending_approval("zohair", ORDER, ttl_seconds=-1)
    assert store.claim_pending_approval(approval_id, "zohair") is None

    row = store.get_pending_approval(approval_id, "zohair")
    assert row is not None and row["status"] == "expired"


def test_expired_approval_drops_out_of_the_pending_list(store):
    store.create_pending_approval("zohair", ORDER, ttl_seconds=-1)
    assert store.list_pending_approvals("zohair") == []
    assert store.count_pending_approvals("zohair") == 0
    # ...but is still visible when resolved rows are requested
    all_rows = store.list_pending_approvals("zohair", include_resolved=True)
    assert len(all_rows) == 1 and all_rows[0]["status"] == "expired"


def test_approvals_are_scoped_to_the_owning_user(store):
    approval_id = store.create_pending_approval("zohair", ORDER)
    assert store.get_pending_approval(approval_id, "someone-else") is None
    assert store.claim_pending_approval(approval_id, "someone-else") is None
    assert store.list_pending_approvals("someone-else") == []
    # and the real owner can still claim it afterwards
    assert store.claim_pending_approval(approval_id, "zohair") is not None


def test_unknown_id_is_handled(store):
    assert store.get_pending_approval("nope", "zohair") is None
    assert store.claim_pending_approval("nope", "zohair") is None


def test_resolve_records_result_and_refuses_to_overwrite(store):
    approval_id = store.create_pending_approval("zohair", ORDER)
    assert store.claim_pending_approval(approval_id, "zohair") is not None

    assert store.resolve_pending_approval(
        approval_id, "zohair", "placed", {"id": "order-1", "status": "accepted"}
    )

    row = store.get_pending_approval(approval_id, "zohair")
    assert row is not None
    assert row["status"] == "placed"
    assert row["result"]["id"] == "order-1"

    # A terminal state must not be rewritten by a late second decision.
    assert not store.resolve_pending_approval(approval_id, "zohair", "failed", {})
    assert store.get_pending_approval(approval_id, "zohair")["status"] == "placed"


def test_reject_leaves_it_unplaceable(store):
    approval_id = store.create_pending_approval("zohair", ORDER)
    assert store.resolve_pending_approval(approval_id, "zohair", "rejected")
    assert store.claim_pending_approval(approval_id, "zohair") is None
    assert store.count_pending_approvals("zohair") == 0


def test_count_pending_for_run_caps_a_runaway_loop(store):
    assert store.count_pending_for_run("cfg1", "zohair") == 0
    for _ in range(3):
        store.create_pending_approval("zohair", ORDER, config_id="cfg1")
    assert store.count_pending_for_run("cfg1", "zohair") == 3
    # a different config is unaffected
    assert store.count_pending_for_run("cfg2", "zohair") == 0


def test_order_json_survives_the_round_trip(store):
    approval_id = store.create_pending_approval("zohair", ORDER)
    row = store.get_pending_approval(approval_id, "zohair")
    assert row is not None
    assert row["order"] == ORDER


def test_corrupt_order_json_does_not_crash_the_listing(store):
    """A malformed row should degrade to an empty order, not break the endpoint."""
    store.create_pending_approval("zohair", ORDER)
    conn = store._get_conn()
    conn.execute("UPDATE pending_trade_approvals SET order_json = 'not json'")
    conn.commit()
    conn.close()

    pending = store.list_pending_approvals("zohair")
    assert len(pending) == 1 and pending[0]["order"] == {}
