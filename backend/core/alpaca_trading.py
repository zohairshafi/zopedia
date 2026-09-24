"""Alpaca trading client — order placement, cancellation, and account reads.

Separate from `core.llm` (which handles market *data*): this module owns
everything that can move money, so there is exactly one place to audit.

Two design rules drive the shape here:

1. **Never lose Alpaca's error message.** The existing market-data helper
   returns `None` on any non-200, throwing away the status code and body. For a
   trading tool that is the single most important information there is (403
   insufficient buying power vs 422 duplicate client_order_id vs 422 bad symbol),
   so this module keeps the status and Alpaca's `message` verbatim.

2. **Never submit without an explicit decision.** Nothing here is called by the
   model directly — `place_order` is invoked only after a human approves, either
   by the chat tool branch or by the pending-approval endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from core.llm import _alpaca_headers, alpaca_configured

logger = logging.getLogger(__name__)

_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_LIVE_BASE_URL = "https://api.alpaca.markets"

_REQUEST_TIMEOUT_SECONDS = 15


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("alpaca: %s=%r is not an integer; using %d", name, raw, default)
        return default


def trading_base_url() -> str:
    """Resolve the Alpaca trading host. Paper unless explicitly overridden."""
    explicit = os.getenv("ZOPEDIA_ALPACA_TRADING_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    return _PAPER_BASE_URL if _env_bool("ZOPEDIA_ALPACA_PAPER", True) else _LIVE_BASE_URL


def is_paper() -> bool:
    return trading_base_url() != _LIVE_BASE_URL


def approval_ttl_seconds() -> int:
    return _env_int("ZOPEDIA_ALPACA_APPROVAL_TTL_SECONDS", 86400)


def chat_approval_timeout_seconds() -> int:
    return _env_int("ZOPEDIA_ALPACA_APPROVAL_CHAT_TIMEOUT_SECONDS", 600)


def max_pending_per_run() -> int:
    return _env_int("ZOPEDIA_ALPACA_MAX_PENDING_PER_RUN", 5)


def _live_refusal() -> str | None:
    """The guardrail: refuse the live host unless explicitly allowed.

    Keyed on the resolved base URL, so it also catches a *live* base URL passed
    via ZOPEDIA_ALPACA_TRADING_BASE_URL — not just ZOPEDIA_ALPACA_PAPER=false.
    """
    if trading_base_url() != _LIVE_BASE_URL:
        return None
    if _env_bool("ZOPEDIA_ALPACA_ALLOW_LIVE", False):
        return None
    return (
        "Refusing to submit to the LIVE Alpaca account. This is a safety gate, "
        "not an error in your request. Set ZOPEDIA_ALPACA_ALLOW_LIVE=true to "
        "trade with real money, or ZOPEDIA_ALPACA_PAPER=true for the paper account."
    )


@dataclass
class AlpacaResult:
    """Outcome of an Alpaca call. Never raises — always returns one of these."""

    ok: bool
    status_code: int | None = None
    data: Any = None
    error_message: str | None = None
    error_code: int | None = None
    transport_error: str | None = None

    def as_error_dict(self, context: str) -> dict[str, Any]:
        """Flatten into the dict shape the tool results use."""
        out: dict[str, Any] = {"error": f"{context}: {self.describe()}"}
        if self.status_code is not None:
            out["status_code"] = self.status_code
        if self.error_code is not None:
            out["alpaca_code"] = self.error_code
        return out

    def describe(self) -> str:
        if self.transport_error:
            return f"could not reach Alpaca ({self.transport_error})"
        if self.error_message:
            return self.error_message
        return f"Alpaca returned HTTP {self.status_code}"


def _request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
) -> AlpacaResult:
    """Sync HTTP call — always invoked via asyncio.to_thread.

    Returns an AlpacaResult rather than raising so the caller can surface
    Alpaca's own message verbatim.
    """
    if not alpaca_configured():
        return AlpacaResult(
            ok=False,
            error_message=(
                "Alpaca API keys are not configured. Set ZOPEDIA_ALPACA_API_KEY "
                "and ZOPEDIA_ALPACA_API_SECRET."
            ),
        )

    import httpx

    url = f"{trading_base_url()}{path}"
    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            resp = client.request(
                method, url, json=json_body, params=params, headers=_alpaca_headers()
            )
    except Exception as exc:  # network-level failure
        logger.warning("alpaca: %s %s transport error: %s", method, path, exc)
        return AlpacaResult(ok=False, transport_error=str(exc))

    body: Any = None
    try:
        body = resp.json() if resp.content else None
    except Exception:
        body = None

    if resp.status_code >= 400:
        # Keep Alpaca's wording — the user and the model both need to see the
        # real reason ("insufficient buying power", "market is closed", ...).
        message = None
        code = None
        if isinstance(body, dict):
            message = body.get("message")
            code = body.get("code")
        if not message:
            message = (resp.text or "")[:300] or None
        logger.warning(
            "alpaca: %s %s -> %d: %.300s", method, path, resp.status_code, resp.text
        )
        return AlpacaResult(
            ok=False,
            status_code=resp.status_code,
            data=body,
            error_message=message,
            error_code=code,
        )

    return AlpacaResult(ok=True, status_code=resp.status_code, data=body)


async def _arequest(
    method: str, path: str, *, json_body: dict | None = None, params: dict | None = None
) -> AlpacaResult:
    return await asyncio.to_thread(
        _request, method, path, json_body=json_body, params=params
    )


# ── Account reads ────────────────────────────────────────────────────


async def get_account() -> AlpacaResult:
    return await _arequest("GET", "/v2/account")


async def get_positions() -> AlpacaResult:
    return await _arequest("GET", "/v2/positions")


async def get_orders(
    status: str = "open", *, symbols: str | None = None, limit: int = 100
) -> AlpacaResult:
    # Alpaca groups orders as open/closed/all — distinct from an individual
    # order's status, so this is passed through as-is rather than mapped.
    params: dict[str, Any] = {"status": status, "limit": limit, "direction": "desc"}
    if symbols:
        params["symbols"] = symbols
    return await _arequest("GET", "/v2/orders", params=params)


async def get_clock() -> AlpacaResult:
    return await _arequest("GET", "/v2/clock")


async def lookup_option_contract(symbol: str) -> AlpacaResult:
    """Validate a specific OSI contract. Unknown symbol -> 404 with Alpaca's message.

    Uses the single-contract endpoint because the *list* endpoint filters by
    `underlying_symbols`, not by an exact contract symbol.
    """
    return await _arequest("GET", f"/v2/options/contracts/{symbol}")


# ── Order model + validation ─────────────────────────────────────────

_SIDES = {"buy", "sell"}
_ORDER_TYPES = {"market", "limit", "stop", "stop_limit", "trailing_stop"}
_TIME_IN_FORCE = {"day", "gtc", "opg", "cls", "ioc", "fok"}
_ORDER_CLASSES = {"simple", "bracket", "oco", "oto", "mleg"}
_POSITION_INTENTS = {"buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"}
_ASSET_TYPES = {"equity", "option"}


@dataclass
class OrderRequest:
    """The single normalized shape that reaches the approval card, the pending
    queue row, and `place_order`. Nothing re-parses model output after approval."""

    symbol: str
    asset_type: str
    side: str
    order_type: str
    time_in_force: str
    qty: float | None = None
    notional: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    trail_price: float | None = None
    trail_percent: float | None = None
    extended_hours: bool | None = None
    order_class: str | None = None
    position_intent: str | None = None
    legs: list[dict] | None = None
    rationale: str | None = None
    client_order_id: str = ""
    # Set when position_intent was derived rather than supplied, so the card can
    # show the user that it was inferred on their behalf.
    derived_position_intent: bool = False
    # Populated by pre-flight, for display only — never sent to Alpaca.
    contract: dict | None = None

    def to_alpaca_payload(self) -> dict[str, Any]:
        """Alpaca body. Omits None so we never send `"limit_price": null`."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "side": self.side,
            "type": self.order_type,
            "time_in_force": self.time_in_force,
        }
        for key in (
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
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.client_order_id:
            payload["client_order_id"] = self.client_order_id
        return payload

    def to_dict(self) -> dict[str, Any]:
        """Full record (including display-only fields) for storage/cards."""
        return asdict(self)

    def summary(self) -> str:
        """One-line human description, used in tool_status and logs."""
        amount = (
            f"{self.qty:g}" if self.qty is not None else f"${self.notional:,.2f}"
        )
        unit = "contract(s)" if self.asset_type == "option" else "share(s)"
        price = ""
        if self.limit_price is not None:
            price = f" @ limit {self.limit_price:g}"
        elif self.stop_price is not None:
            price = f" @ stop {self.stop_price:g}"
        return f"{self.side.upper()} {amount} {unit} {self.symbol}{price} ({self.order_type}, {self.time_in_force})"


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_order_request(args: dict) -> tuple[OrderRequest | None, list[str]]:
    """Validate raw tool arguments into an OrderRequest.

    Returns EVERY problem at once rather than the first, so the model can fix
    them all in a single turn. On failure the request is None and the caller
    must not show an approval card or queue anything.
    """
    problems: list[str] = []

    symbol = str(args.get("symbol") or "").strip().upper()
    asset_type = str(args.get("asset_type") or "").strip().lower()
    side = str(args.get("side") or "").strip().lower()
    order_type = str(args.get("type") or "").strip().lower()
    tif = str(args.get("time_in_force") or "").strip().lower()

    if not symbol:
        problems.append("symbol is required.")
    if asset_type not in _ASSET_TYPES:
        problems.append("asset_type must be 'equity' or 'option'.")
    if side not in _SIDES:
        problems.append("side must be 'buy' or 'sell'.")
    if order_type not in _ORDER_TYPES:
        problems.append(
            "type must be one of market, limit, stop, stop_limit, trailing_stop."
        )
    if tif not in _TIME_IN_FORCE:
        problems.append("time_in_force must be one of day, gtc, opg, cls, ioc, fok.")

    qty = _as_float(args.get("qty"))
    notional = _as_float(args.get("notional"))
    limit_price = _as_float(args.get("limit_price"))
    stop_price = _as_float(args.get("stop_price"))
    trail_price = _as_float(args.get("trail_price"))
    trail_percent = _as_float(args.get("trail_percent"))

    if qty is not None and notional is not None:
        problems.append("Provide qty OR notional, not both.")
    elif qty is None and notional is None:
        problems.append("One of qty or notional is required.")

    if qty is not None and qty <= 0:
        problems.append("qty must be greater than zero.")
    if notional is not None:
        if notional <= 0:
            problems.append("notional must be greater than zero.")
        if asset_type == "option":
            # Alpaca only allows notional for equity market-day orders.
            problems.append("notional is not valid for options; use qty (contracts).")
        if order_type != "market" or tif != "day":
            problems.append("notional requires type='market' and time_in_force='day'.")

    if asset_type == "option" and qty is not None and qty != int(qty):
        problems.append("Options qty must be a whole number of contracts.")

    if order_type in {"limit", "stop_limit"} and limit_price is None:
        problems.append(f"limit_price is required for type='{order_type}'.")
    if order_type in {"stop", "stop_limit"} and stop_price is None:
        problems.append(f"stop_price is required for type='{order_type}'.")
    if order_type == "trailing_stop":
        if (trail_price is None) == (trail_percent is None):
            problems.append(
                "type='trailing_stop' requires exactly one of trail_price or trail_percent."
            )

    extended_hours = args.get("extended_hours")
    if extended_hours:
        if order_type != "limit":
            problems.append("extended_hours is only valid with type='limit'.")
        if tif not in {"day", "gtc"}:
            problems.append("extended_hours requires time_in_force 'day' or 'gtc'.")

    order_class = str(args.get("order_class") or "simple").strip().lower()
    if order_class not in _ORDER_CLASSES:
        problems.append(
            "order_class must be one of simple, bracket, oco, oto, mleg."
        )
    legs = args.get("legs")
    if order_class == "mleg":
        if not isinstance(legs, list) or not legs:
            problems.append("order_class='mleg' requires legs.")
        elif len(legs) > 4:
            problems.append("At most 4 legs are supported.")
    elif legs:
        problems.append("legs is only valid with order_class='mleg'.")

    position_intent = args.get("position_intent")
    derived_intent = False
    if asset_type == "option":
        if position_intent:
            position_intent = str(position_intent).strip().lower()
            if position_intent not in _POSITION_INTENTS:
                problems.append(
                    "position_intent must be one of buy_to_open, buy_to_close, "
                    "sell_to_open, sell_to_close."
                )
        elif side in _SIDES:
            # Derive, but flag it so the card shows the user what was inferred.
            position_intent = "buy_to_open" if side == "buy" else "sell_to_close"
            derived_intent = True
    elif position_intent:
        problems.append("position_intent is only valid for options.")

    if problems:
        return None, problems

    return (
        OrderRequest(
            symbol=symbol,
            asset_type=asset_type,
            side=side,
            order_type=order_type,
            time_in_force=tif,
            qty=qty,
            notional=notional,
            limit_price=limit_price,
            stop_price=stop_price,
            trail_price=trail_price,
            trail_percent=trail_percent,
            extended_hours=bool(extended_hours) if extended_hours is not None else None,
            order_class=order_class if order_class != "simple" else None,
            position_intent=position_intent,
            legs=legs,
            rationale=(str(args.get("rationale")).strip() or None)
            if args.get("rationale")
            else None,
            client_order_id=str(args.get("client_order_id") or "").strip(),
            derived_position_intent=derived_intent,
        ),
        [],
    )


# ── Pre-flight ───────────────────────────────────────────────────────


async def preflight(req: OrderRequest) -> tuple[dict[str, Any], list[str]]:
    """Gather the context the approval card needs, and fail loudly on anything
    that would make the order un-placeable — BEFORE the user is asked to approve.

    Returns (context, problems). Non-empty problems means: do not show a card.
    """
    problems: list[str] = []
    context: dict[str, Any] = {
        "base_url": trading_base_url(),
        "paper": is_paper(),
    }

    clock = await get_clock()
    if clock.ok and isinstance(clock.data, dict):
        context["market_open"] = bool(clock.data.get("is_open"))
        context["next_open"] = clock.data.get("next_open")
        context["next_close"] = clock.data.get("next_close")
    else:
        # Don't assert a market state we couldn't verify.
        context["market_open"] = None
        context["market_state_note"] = f"Market state unknown ({clock.describe()})."

    account = await get_account()
    if account.ok and isinstance(account.data, dict):
        acct = account.data
        context["account_summary"] = {
            "cash": acct.get("cash"),
            "buying_power": acct.get("buying_power"),
            "portfolio_value": acct.get("portfolio_value"),
            "equity": acct.get("equity"),
        }
        if acct.get("trading_blocked") or acct.get("account_blocked"):
            problems.append("The Alpaca account is blocked for trading.")
        if req.asset_type == "option":
            level = acct.get("options_approved_level")
            if level is None:
                level = acct.get("options_trading_level")
            context["options_level"] = level
            if level is not None and int(level) < 1:
                problems.append(
                    "This Alpaca account is not approved for options trading "
                    f"(options level {level})."
                )
    else:
        problems.append(f"Could not read the Alpaca account: {account.describe()}")

    if req.asset_type == "option":
        contract = await lookup_option_contract(req.symbol)
        if contract.ok and isinstance(contract.data, dict):
            c = contract.data
            if not c.get("tradable", True):
                problems.append(f"Option contract {req.symbol} is not currently tradable.")
            context["contract"] = {
                "symbol": c.get("symbol"),
                "underlying": c.get("underlying_symbol"),
                "type": c.get("type"),
                "strike_price": c.get("strike_price"),
                "expiration_date": c.get("expiration_date"),
                "multiplier": c.get("multiplier"),
                "status": c.get("status"),
            }
        else:
            # Alpaca's 404 message names the exact symbol it couldn't find.
            problems.append(f"Not a tradable option contract: {contract.describe()}")

    return context, problems


async def place_order(req: OrderRequest) -> AlpacaResult:
    """Submit an order. Only ever called after an explicit human approval."""
    refusal = _live_refusal()
    if refusal:
        logger.warning("alpaca: refused live order for %s", req.symbol)
        return AlpacaResult(ok=False, error_message=refusal)

    if not req.client_order_id:
        req.client_order_id = f"zop-{uuid.uuid4().hex[:24]}"

    logger.info("alpaca: submitting order %s", req.summary())
    return await _arequest("POST", "/v2/orders", json_body=req.to_alpaca_payload())


async def cancel_order(order_id: str) -> AlpacaResult:
    """Cancel a working order by id."""
    refusal = _live_refusal()
    if refusal:
        return AlpacaResult(ok=False, error_message=refusal)

    if not order_id:
        return AlpacaResult(ok=False, error_message="order_id is required.")

    logger.info("alpaca: cancelling order %s", order_id)
    return await _arequest("DELETE", f"/v2/orders/{order_id}")


# ── Tool executors ───────────────────────────────────────────────────
# These return json.dumps(...) strings and never raise, matching the existing
# alpaca_market_data / alpaca_news executors.


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


async def execute_alpaca_account(
    section: str,
    order_status: str = "open",
    symbol: str | None = None,
    limit: int = 100,
) -> str:
    """Read-only account access. Safe to expose anywhere, including headless runs."""
    section = (section or "").strip().lower()

    if section == "summary":
        result = await get_account()
        if not result.ok:
            return _dump(result.as_error_dict("Alpaca account read failed"))
        data = dict(result.data or {})
        # Never leak the account number into model context.
        data.pop("account_number", None)
        return _dump(
            {
                "account": data,
                "trading_base_url": trading_base_url(),
                "paper": is_paper(),
            }
        )

    if section == "positions":
        result = await get_positions()
        if not result.ok:
            return _dump(result.as_error_dict("Alpaca positions read failed"))
        positions = result.data or []
        if symbol:
            want = symbol.strip().upper()
            positions = [p for p in positions if str(p.get("symbol", "")).upper() == want]
        return _dump({"count": len(positions), "positions": positions})

    if section == "orders":
        result = await get_orders(order_status, symbols=symbol, limit=limit)
        if not result.ok:
            return _dump(result.as_error_dict("Alpaca orders read failed"))
        orders = result.data or []
        trimmed = [
            {
                k: o.get(k)
                for k in (
                    "id",
                    "client_order_id",
                    "symbol",
                    "side",
                    "qty",
                    "notional",
                    "type",
                    "time_in_force",
                    "status",
                    "filled_qty",
                    "filled_avg_price",
                    "limit_price",
                    "stop_price",
                    "submitted_at",
                    "filled_at",
                    "canceled_at",
                )
            }
            for o in orders
        ]
        return _dump({"count": len(trimmed), "status_filter": order_status, "orders": trimmed})

    if section == "clock":
        result = await get_clock()
        if not result.ok:
            return _dump(result.as_error_dict("Alpaca clock read failed"))
        return _dump({"clock": result.data, "paper": is_paper()})

    return _dump(
        {
            "error": "section must be one of summary, positions, orders, clock.",
        }
    )


async def execute_alpaca_cancel(order_id: str) -> str:
    result = await cancel_order(order_id)
    if not result.ok:
        return _dump(result.as_error_dict("Alpaca cancel failed"))
    return _dump({"status": "canceled", "order": result.data})
