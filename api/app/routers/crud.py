import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from supabase import Client

from app.db.client import get_authenticated_supabase

logger = logging.getLogger(__name__)
router = APIRouter()

# Lista permitida estricta: nunca se usa directamente una tabla indicada por el
# usuario sin traducirla mediante este mapa.
TABLE_MAP: dict[str, str] = {
    "profiles": "profiles",
    "user-access": "user_access",
    "categories": "categories",
    "zones": "zones",
    "user-interests": "user_interests",
    "businesses": "businesses",
    "places": "places",
    "place-categories": "place_categories",
    "opening-hours": "opening_hours",
    "place-media": "place_media",
    "routes": "routes",
    "route-stops": "route_stops",
    "saved-routes": "saved_routes",
    "reviews": "reviews",
    "review-media": "review_media",
    "review-replies": "review_replies",
    "subscription-plans": "subscription_plans",
    "subscriptions": "subscriptions",
    "offline-downloads": "offline_downloads",
    "promotions": "promotions",
    "coupon-redemptions": "coupon_redemptions",
    "experiences": "experiences",
    "reservations": "reservations",
    "campaigns": "campaigns",
    "campaign-events": "campaign_events",
    "place-visits": "place_visits",
    "business-verifications": "business_verifications",
    "tickets": "tickets",
    "ticket-messages": "ticket_messages",
    "notifications": "notifications",
    "moderation-actions": "moderation_actions",
    "audit-logs": "audit_logs",
}

# Solo se permite filtrar por columnas que existen en cada entidad. Los permisos
# de lectura y escritura los continúa determinando RLS en PostgreSQL.
FILTERABLE_COLUMNS: dict[str, set[str]] = {
    "place_id": {
        "place_categories",
        "opening_hours",
        "place_media",
        "route_stops",
        "reviews",
        "promotions",
        "experiences",
        "place_visits",
        "tickets",
    },
    "route_id": {"route_stops", "saved_routes", "offline_downloads", "tickets"},
    "business_id": {
        "places",
        "review_replies",
        "promotions",
        "experiences",
        "campaigns",
        "business_verifications",
    },
    "category_id": {"user_interests", "place_categories", "routes", "campaigns"},
}


def _get_table(entity: str) -> str:
    table = TABLE_MAP.get(entity)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entidad no encontrada.")
    return table


def _raise_database_error(exc: Exception) -> None:
    code = str(getattr(exc, "code", "") or "")
    if code == "42501":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operación no autorizada por las políticas de acceso.") from exc
    if code == "23505":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El registro entra en conflicto con uno existente.") from exc
    if code in {"23503", "23514", "22P02", "22023"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Los datos no cumplen las restricciones de la base de datos.") from exc
    if code == "PGRST116":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado.") from exc

    logger.warning("Error de Supabase al operar CRUD (%s)", code or type(exc).__name__)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="No se pudo completar la operación en la base de datos.",
    ) from exc


def _apply_filters(query: Any, table: str, filters: dict[str, UUID | None]) -> Any:
    for column, value in filters.items():
        if value is None:
            continue
        if table not in FILTERABLE_COLUMNS[column]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El filtro '{column}' no está disponible para esta entidad.",
            )
        query = query.eq(column, str(value))
    return query


@router.get("/{entity}", summary="Listar registros de una entidad")
def list_records(
    entity: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    place_id: UUID | None = Query(default=None),
    route_id: UUID | None = Query(default=None),
    business_id: UUID | None = Query(default=None),
    category_id: UUID | None = Query(default=None),
    db: Client = Depends(get_authenticated_supabase),
) -> list[dict[str, Any]]:
    table = _get_table(entity)
    try:
        query = db.table(table).select("*")
        query = _apply_filters(
            query,
            table,
            {
                "place_id": place_id,
                "route_id": route_id,
                "business_id": business_id,
                "category_id": category_id,
            },
        )
        result = query.range(offset, offset + limit - 1).execute()
        return result.data or []
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


@router.post(
    "/{entity}",
    status_code=status.HTTP_201_CREATED,
    summary="Crear un registro",
)
def create_record(
    entity: str,
    payload: dict[str, Any] = Body(...),
    db: Client = Depends(get_authenticated_supabase),
) -> dict[str, Any]:
    table = _get_table(entity)
    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El cuerpo de creación no puede estar vacío.")
    try:
        result = db.table(table).insert(payload).select("*").execute()
        if not result.data:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="La base de datos no devolvió el registro creado.")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


@router.get("/{entity}/{record_id}", summary="Obtener un registro por ID")
def get_record(
    entity: str,
    record_id: UUID,
    db: Client = Depends(get_authenticated_supabase),
) -> dict[str, Any]:
    table = _get_table(entity)
    try:
        result = (
            db.table(table)
            .select("*")
            .eq("id", str(record_id))
            .maybe_single()
            .execute()
        )
        if result.data is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado.")
        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


@router.patch("/{entity}/{record_id}", summary="Actualizar parcialmente un registro")
def update_record(
    entity: str,
    record_id: UUID,
    payload: dict[str, Any] = Body(...),
    db: Client = Depends(get_authenticated_supabase),
) -> dict[str, Any]:
    table = _get_table(entity)
    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El cuerpo de actualización no puede estar vacío.")
    if "id" in payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No se permite cambiar el ID del registro.")
    try:
        result = (
            db.table(table)
            .update(payload)
            .eq("id", str(record_id))
            .select("*")
            .maybe_single()
            .execute()
        )
        if result.data is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado o no visible para este usuario.")
        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


@router.delete(
    "/{entity}/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Eliminar un registro",
)
def delete_record(
    entity: str,
    record_id: UUID,
    db: Client = Depends(get_authenticated_supabase),
) -> Response:
    table = _get_table(entity)
    try:
        result = db.table(table).delete().eq("id", str(record_id)).select("id").execute()
        if not result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado o no visible para este usuario.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)
