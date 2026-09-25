"""Date handling on the options chain — no network, no Alpaca calls.

Two things are pinned here.

First, the validator must agree with Alpaca about what a date looks like. Alpaca
parses with Go's "2006-01-02" layout, which is strict, and neither stdlib parser
matches it on its own: `strptime` accepts the unpadded "2026-9-25", and
`date.fromisoformat` accepts the basic "20260925" from Python 3.11 onward — the
server image is 3.12, so a lenient check would pass values Alpaca rejects. A
rejected date comes back as a 400, which the caller reports as "no options
snapshots returned", and that is indistinguishable from a genuinely empty chain.
That misleading shape is what let a model conclude puts did not exist.

Second, a malformed date must be caught BEFORE the request goes out, so the model
gets a fixable message instead of a false "no data". The fake request below fails
the test if it is ever reached with a bad date.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.llm as llm  # noqa: E402

# Forms Alpaca rejects with 400, verified against the live paper account —
# including the two that a naive stdlib check would wrongly accept.
BAD_DATES = [
    "20260925",            # fromisoformat accepts this on 3.11+
    "2026-9-25",           # strptime accepts this
    "25/09/2026",
    "2026-09-25T00:00:00",
    "2026-13-45",
    "2026-02-30",
    "not-a-date",
]

GOOD_DATES = ["2026-09-25", "2027-01-01", "2027-03-31"]


@pytest.fixture
def alpaca(monkeypatch):
    """Configure fake credentials and capture the outgoing request."""
    monkeypatch.setattr(llm, "_ALPACA_API_KEY", "test-key-id")
    monkeypatch.setattr(llm, "_ALPACA_API_SECRET", "test-secret")
    seen: dict = {}

    def fake_request(url, params):
        seen["url"] = url
        seen["params"] = params
        return {"snapshots": {}, "next_page_token": None}

    monkeypatch.setattr(llm, "_alpaca_request", fake_request)
    return seen


def run_chain(**kwargs):
    return asyncio.run(llm.execute_alpaca_market_data("AAPL", "options_chain", **kwargs))


@pytest.mark.parametrize("bad", BAD_DATES)
def test_malformed_date_is_rejected_before_any_request(alpaca, bad):
    out = json.loads(run_chain(expiration_date_gte=bad))

    assert "error" in out
    # The message must be actionable and must not read as an empty result.
    assert "YYYY-MM-DD" in out["error"]
    assert "no options snapshots returned" not in out["error"], (
        "a rejected date must not be reported as an empty chain — that is the "
        "misleading shape this test exists to prevent"
    )
    assert "url" not in alpaca, "the request must not be sent with an invalid date"

    for field in ("expiration_date", "expiration_date_lte"):
        assert "error" in json.loads(run_chain(**{field: bad}))


@pytest.mark.parametrize("good", GOOD_DATES)
def test_valid_dates_are_sent(alpaca, good):
    run_chain(expiration_date_gte=good)
    assert alpaca["params"]["expiration_date_gte"] == good


def test_range_and_filters_reach_the_request(alpaca):
    out = json.loads(
        run_chain(
            option_type="put",
            expiration_date_gte="2027-01-01",
            expiration_date_lte="2027-03-31",
        )
    )

    assert alpaca["params"]["type"] == "put"
    assert alpaca["params"]["expiration_date_gte"] == "2027-01-01"
    assert alpaca["params"]["expiration_date_lte"] == "2027-03-31"
    # No limit given means the endpoint's maximum, not an invented small default.
    assert alpaca["params"]["limit"] == 1000
    assert out["filters_applied"] == {
        "type": "put",
        "expiration_date_gte": "2027-01-01",
        "expiration_date_lte": "2027-03-31",
    }


def test_explicit_limit_is_honoured_below_the_endpoint_maximum(alpaca):
    run_chain(option_type="put", limit=7)
    assert alpaca["params"]["limit"] == 7

    # Above the documented maximum it clamps rather than sending a 400.
    run_chain(option_type="put", limit=5000)
    assert alpaca["params"]["limit"] == 1000
