"""Trading routes — the pending-approval queue for headless research.

Orders proposed by a headless research run land here and wait. Approving one
executes it *outside any generation*: no model, no tool loop, nothing but the
stored OrderRequest that the user is looking at. That is deliberate — the fields
on the card are the fields submitted.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from core.alpaca_trading import OrderRequest, place_order

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_username(request: Request) -> str:
    """Authenticated username. Mirrors routes/periodic.py — the 401 must
    propagate so the frontend refreshes its token and retries."""
    require_valid = getattr(request.app.state, "require_valid_subject", None)
    if require_valid:
        return await require_valid(request)
    return "default"


@router.get("/api/trading/pending-approvals")
async def list_pending_approvals(request: Request):
    """Orders queued by research runs, awaiting the user's decision."""
    from periodic_store import count_pending_approvals, list_pending_approvals

    username = await _get_username(request)
    approvals = list_pending_approvals(username)
    return {
        "approvals": approvals,
        "pending_count": count_pending_approvals(username),
    }


@router.post("/api/trading/pending-approvals/{approval_id}/approve")
async def approve_pending_approval(request: Request, approval_id: str):
    """Approve a queued order and submit it to Alpaca.

    The row is claimed atomically first: if that fails the order is already
    decided or has expired, and we must not place anything.
    """
    from periodic_store import (
        claim_pending_approval,
        get_pending_approval,
        resolve_pending_approval,
    )

    username = await _get_username(request)

    # Look first, purely so we can give the caller an accurate reason.
    existing = get_pending_approval(approval_id, username)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found."
        )

    claimed = claim_pending_approval(approval_id, username)
    if claimed is None:
        if existing["status"] == "expired":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=(
                    f"This order expired at {existing['expires_at']} and was NOT "
                    "placed. Place it again if you still want it."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This order was already {existing['status']} and was not placed again."
            ),
        )

    try:
        req = OrderRequest(**claimed["order"])
    except TypeError as exc:
        # Stored shape no longer matches the model — fail loudly rather than
        # guessing at fields and submitting something the user never saw.
        resolve_pending_approval(approval_id, username, "failed", {"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stored order could not be rebuilt: {exc}",
        )

    result = await place_order(req)

    if result.ok:
        resolve_pending_approval(approval_id, username, "placed", result.data)
        return {
            "status": "placed",
            "order": result.data,
            "approval_id": approval_id,
        }

    error = result.as_error_dict("Alpaca rejected the order")
    resolve_pending_approval(approval_id, username, "failed", error)
    logger.warning("trading: queued order %s failed: %s", approval_id, error)
    # 502: we reached Alpaca and it refused, which is not the client's fault.
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error)


@router.post("/api/trading/pending-approvals/{approval_id}/reject")
async def reject_pending_approval(request: Request, approval_id: str):
    """Decline a queued order. Nothing is ever sent to Alpaca."""
    from periodic_store import get_pending_approval, resolve_pending_approval

    username = await _get_username(request)

    existing = get_pending_approval(approval_id, username)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found."
        )

    if not resolve_pending_approval(approval_id, username, "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This order was already {existing['status']}.",
        )

    return {"status": "rejected", "approval_id": approval_id}
