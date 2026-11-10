import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.db.client import get_required_authenticated_supabase
from app.schemas.actions import BookExperienceRequest, RedeemCouponRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def _raise_rpc_error(exc: Exception) -> None:
    code = str(getattr(exc, "code", "") or "")
    message = str(getattr(exc, "message", "") or "").lower()
    if code == "42501" or "unauthorized" in message or "forbidden" in message:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operación no autorizada.") from exc
    if "not found" in message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El recurso solicitado no existe.") from exc
    if "idempotency conflict" in message:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="request_key ya fue usado para otra operación.") from exc
    if code == "22023" or "limit reached" in message or "no capacity" in message or "unavailable" in message:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La operación no está disponible con los datos actuales.") from exc
    if isinstance(exc, APIError):
        logger.warning("Error en RPC de Supabase (%s)", code or type(exc).__name__)
    else:
        logger.exception("Error inesperado al ejecutar RPC")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="No se pudo completar la operación transaccional.",
    ) from exc


@router.post(
    "/promotions/{promotion_id}/redeem",
    summary="Redeem",
    description=(
        "Canjear una promoción mediante el RPC atómico "
        "redeem_coupon(promotion, request_key, purchase_amount)."
    ),
)
def redeem_promotion(
    promotion_id: UUID,
    payload: RedeemCouponRequest,
    db: Client = Depends(get_required_authenticated_supabase),
) -> Any:
    try:
        response = db.rpc(
            "redeem_coupon",
            {
                "promotion": str(promotion_id),
                "request_key": str(payload.request_key),
                "purchase_amount": payload.purchase_amount,
            },
        ).execute()
        return response.data
    except HTTPException:
        raise
    except Exception as exc:
        _raise_rpc_error(exc)


@router.post(
    "/experiences/{experience_id}/reserve",
    summary="Reserve",
    description=(
        "Reservar una experiencia mediante el RPC atómico "
        "book_experience(experience, people, request_key)."
    ),
)
def reserve_experience(
    experience_id: UUID,
    payload: BookExperienceRequest,
    db: Client = Depends(get_required_authenticated_supabase),
) -> Any:
    try:
        response = db.rpc(
            "book_experience",
            {
                "experience": str(experience_id),
                "people": payload.people,
                "request_key": str(payload.request_key),
            },
        ).execute()
        return response.data
    except HTTPException:
        raise
    except Exception as exc:
        _raise_rpc_error(exc)
