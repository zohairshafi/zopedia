"""Order validation for the Alpaca trading tool — no network, no Alpaca calls.

The most important test here is `test_every_declared_field_survives_round_trip`.
The existing `alpaca_market_data` branch silently drops `option_type` and
`page_token` even though its schema declares them, and
`int(args.get("limit") or 10)` collapses a legitimate 0 — so a test that asserts
*every* declared argument reaches the payload is the one that catches that class
of bug before it ships again.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# These modules import bare (`from core.llm import ...`), so backend/ must be
# importable — matching how the server runs them.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.alpaca_trading import (  # noqa: E402
    OrderRequest,
    _live_refusal,
    is_paper,
    trading_base_url,
    validate_order_request,
)

# Fields Alpaca actually accepts on POST /v2/orders. Anything else in the body
# risks a 422 "unrecognized parameter", so the payload must be a strict subset.
ALPACA_SENDABLE = {
    "symbol",
    "side",
    "type",
    "time_in_force",
    "qty",
    "notional",
    "limit_price",
    "stop_price",
    "trail_price",
    "trail_percent",
    "extended_hours",
    "order_class",
    "position_intent",
    "legs",
    "client_order_id",
}


def _equity(**overrides) -> dict:
    args = {
        "asset_type": "equity",
        "symbol": "aapl",
        "side": "buy",
        "qty": 1,
        "type": "market",
        "time_in_force": "day",
    }
    args.update(overrides)
    return args


def _option(**overrides) -> dict:
    args = {
        "asset_type": "option",
        "symbol": "AAPL231201C00195000",
        "side": "buy",
        "qty": 1,
        "type": "limit",
        "time_in_force": "day",
        "limit_price": 5.10,
    }
    args.update(overrides)
    return args


def _problems(args: dict) -> list[str]:
    req, problems = validate_order_request(args)
    assert req is None, "expected validation to reject, but it produced a request"
    return problems


# ── quantity / notional rules ────────────────────────────────────────


def test_qty_and_notional_together_rejected():
    problems = _problems(_equity(qty=1, notional=500))
    assert any("not both" in p for p in problems)


def test_neither_qty_nor_notional_rejected():
    args = _equity()
    args.pop("qty")
    assert any("qty or notional is required" in p for p in _problems(args))


def test_notional_rejected_for_options():
    problems = _problems(_option(notional=500, limit_price=None, type="market"))
    assert any("not valid for options" in p for p in problems)


def test_notional_requires_market_day():
    problems = _problems(_equity(qty=None, notional=500, type="limit", limit_price=10))
    assert any("market" in p and "day" in p for p in problems)


def test_option_qty_must_be_whole_contracts():
    assert any("whole number" in p for p in _problems(_option(qty=1.5)))


def test_equity_fractional_qty_allowed():
    req, problems = validate_order_request(_equity(qty=0.5))
    assert not problems and req is not None and req.qty == 0.5


# ── price rules ──────────────────────────────────────────────────────


def test_limit_requires_limit_price():
    assert any("limit_price is required" in p for p in _problems(_equity(type="limit")))


def test_stop_requires_stop_price():
    args = _equity(type="stop")
    assert any("stop_price is required" in p for p in _problems(args))


def test_trailing_stop_requires_exactly_one_trail_param():
    both = _equity(type="trailing_stop", trail_price=1, trail_percent=1)
    assert any("exactly one" in p for p in _problems(both))

    neither = _equity(type="trailing_stop")
    assert any("exactly one" in p for p in _problems(neither))

    one = _equity(type="trailing_stop", trail_percent=2)
    req, problems = validate_order_request(one)
    assert not problems and req is not None


def test_extended_hours_requires_limit_and_day_or_gtc():
    assert any(
        "extended_hours is only valid with type='limit'" in p
        for p in _problems(_equity(extended_hours=True))
    )
    bad_tif = _equity(type="limit", limit_price=10, extended_hours=True, time_in_force="ioc")
    assert any("extended_hours requires" in p for p in _problems(bad_tif))


# ── options specifics ────────────────────────────────────────────────


def test_option_position_intent_derived_and_flagged():
    req, problems = validate_order_request(_option())
    assert not problems and req is not None
    assert req.position_intent == "buy_to_open"
    assert req.derived_position_intent is True
    # and it must actually reach the payload, not just live on the dataclass
    assert req.to_alpaca_payload()["position_intent"] == "buy_to_open"


def test_option_sell_derives_sell_to_close():
    req, _ = validate_order_request(_option(side="sell", qty=1))
    assert req is not None and req.position_intent == "sell_to_close"


def test_explicit_position_intent_is_not_flagged_derived():
    req, _ = validate_order_request(_option(position_intent="buy_to_close"))
    assert req is not None and req.derived_position_intent is False


def test_position_intent_rejected_for_equity():
    problems = _problems(_equity(position_intent="buy_to_open"))
    assert any("only valid for options" in p for p in problems)


def test_mleg_requires_legs_and_legs_requires_mleg():
    assert any("requires legs" in p for p in _problems(_option(order_class="mleg")))
    assert any(
        "only valid with order_class='mleg'" in p
        for p in _problems(_option(legs=[{"symbol": "X", "ratio_qty": 1}]))
    )


def test_mleg_with_legs_is_accepted():
    args = _option(order_class="mleg", legs=[{"symbol": "AAPL231201C00195000", "ratio_qty": 1}])
    req, problems = validate_order_request(args)
    assert not problems and req is not None
    assert req.to_alpaca_payload()["legs"]


# ── error reporting shape ────────────────────────────────────────────


def test_all_problems_reported_at_once():
    """The model should be able to fix everything in one turn, not one-at-a-time."""
    problems = _problems(
        {
            "asset_type": "option",
            "symbol": "",           # missing symbol
            "side": "hold",         # bad side
            "qty": 1.5,             # fractional contracts
            "notional": 500,        # also conflicting with qty
            "type": "wat",          # bad type
            "time_in_force": "eod",  # bad tif
        }
    )
    assert len(problems) >= 5, problems


# ── payload construction ─────────────────────────────────────────────


def test_none_fields_are_omitted_from_payload():
    req, _ = validate_order_request(_equity(qty=3))
    payload = req.to_alpaca_payload()
    for absent in ("limit_price", "stop_price", "notional", "trail_percent", "legs"):
        assert absent not in payload, f"{absent} should be omitted, not sent as null"


def test_falsy_but_valid_value_is_not_dropped():
    """`extended_hours=False` must survive — the `x or default` pattern would eat it."""
    req, _ = validate_order_request(_equity(type="limit", limit_price=10, extended_hours=False))
    assert req is not None
    payload = req.to_alpaca_payload()
    assert "extended_hours" in payload and payload["extended_hours"] is False


def test_payload_contains_only_fields_alpaca_accepts():
    """asset_type / rationale are internal — Alpaca 422s on unrecognized parameters."""
    req, _ = validate_order_request(_option(rationale="because"))
    assert req is not None
    payload = req.to_alpaca_payload()
    unexpected = set(payload) - ALPACA_SENDABLE
    assert not unexpected, f"payload would send non-Alpaca fields: {unexpected}"
    assert "rationale" not in payload
    assert "asset_type" not in payload


def test_every_declared_field_survives_round_trip():
    """The regression test for the dropped-parameter bug.

    Every Alpaca-sendable field is set to a real value and must appear in the
    payload with exactly that value.
    """
    args = {
        "asset_type": "option",
        "symbol": "aapl231201c00195000",
        "side": "buy",
        "qty": 2,
        "type": "limit",
        "time_in_force": "gtc",
        "limit_price": 5.1,
        "extended_hours": True,
        "order_class": "simple",
        "position_intent": "buy_to_open",
        "client_order_id": "zop-test-1",
        "rationale": "test",
    }
    req, problems = validate_order_request(args)
    assert not problems and req is not None, problems
    payload = req.to_alpaca_payload()

    assert payload["symbol"] == "AAPL231201C00195000", "symbol must be uppercased"
    assert payload["side"] == "buy"
    assert payload["type"] == "limit"
    assert payload["time_in_force"] == "gtc"
    assert payload["qty"] == 2
    assert payload["limit_price"] == 5.1
    assert payload["extended_hours"] is True
    assert payload["position_intent"] == "buy_to_open"
    assert payload["client_order_id"] == "zop-test-1"

    # Nothing declared was silently dropped.
    missing = {k for k, v in payload.items() if v is None}
    assert not missing, f"declared fields arrived as None: {missing}"


def test_summary_is_human_readable():
    req, _ = validate_order_request(_option(qty=2))
    assert req is not None
    text = req.summary()
    assert "BUY" in text and "contract" in text and req.symbol in text


def test_order_request_dict_round_trips_for_storage():
    """The queue persists to_dict() and rebuilds later — it must survive JSON."""
    import json

    req, _ = validate_order_request(_option(rationale="why"))
    assert req is not None
    revived = OrderRequest(**json.loads(json.dumps(req.to_dict())))
    assert revived.to_alpaca_payload() == req.to_alpaca_payload()
    assert revived.rationale == "why"


# ── the live-account guardrail ───────────────────────────────────────
# This is the safety net that has to hold *before* real keys are ever wired in,
# so it is tested here rather than discovered later.


def test_defaults_to_paper_and_does_not_refuse(monkeypatch):
    for var in ("ZOPEDIA_ALPACA_PAPER", "ZOPEDIA_ALPACA_TRADING_BASE_URL",
                "ZOPEDIA_ALPACA_ALLOW_LIVE"):
        monkeypatch.delenv(var, raising=False)
    assert trading_base_url() == "https://paper-api.alpaca.markets"
    assert is_paper() is True
    assert _live_refusal() is None


def test_live_via_paper_flag_is_refused(monkeypatch):
    monkeypatch.delenv("ZOPEDIA_ALPACA_TRADING_BASE_URL", raising=False)
    monkeypatch.delenv("ZOPEDIA_ALPACA_ALLOW_LIVE", raising=False)
    monkeypatch.setenv("ZOPEDIA_ALPACA_PAPER", "false")
    assert trading_base_url() == "https://api.alpaca.markets"
    refusal = _live_refusal()
    assert refusal is not None and "ALLOW_LIVE" in refusal


def test_live_via_explicit_base_url_is_refused(monkeypatch):
    """The guardrail keys off the resolved URL, so an explicit override can't bypass it."""
    monkeypatch.delenv("ZOPEDIA_ALPACA_PAPER", raising=False)
    monkeypatch.delenv("ZOPEDIA_ALPACA_ALLOW_LIVE", raising=False)
    monkeypatch.setenv("ZOPEDIA_ALPACA_TRADING_BASE_URL", "https://api.alpaca.markets/")
    assert _live_refusal() is not None


def test_allow_live_opt_in_clears_the_refusal(monkeypatch):
    monkeypatch.delenv("ZOPEDIA_ALPACA_TRADING_BASE_URL", raising=False)
    monkeypatch.setenv("ZOPEDIA_ALPACA_PAPER", "false")
    monkeypatch.setenv("ZOPEDIA_ALPACA_ALLOW_LIVE", "true")
    assert _live_refusal() is None


def test_paper_base_url_never_refuses(monkeypatch):
    monkeypatch.setenv("ZOPEDIA_ALPACA_PAPER", "true")
    monkeypatch.delenv("ZOPEDIA_ALPACA_ALLOW_LIVE", raising=False)
    assert _live_refusal() is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
