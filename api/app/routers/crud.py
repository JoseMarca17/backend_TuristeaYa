"""CRUD dirigido por esquema para la API TuristeaYa.

Auditar contra ``db.json`` (32 tablas de PostgreSQL/Supabase) implica tres
reglas que este módulo hace невозмож omitir:

1. Mapeo centralizado URL -> tabla. ``RESOURCES`` traduce cada ruta kebab-case
   (``/api/v1/place-categories``) a su tabla física snake_case
   (``place_categories``) ANTES de invocar ``supabase.table(...)``. Ninguna
   entidad depende de convenciones implícitas: si la tabla no está en el
   diccionario, el router no la expone.

2. El esquema es la única fuente de verdad (``app.core.schema_map``, generado
   desde ``db.json`` con ``tools/generate_schema_map.py``):
   - ``TABLE_COLUMNS``       valida los payloads de POST/PATCH contra las
     columnas reales (un campo inexistente produce 422 y no un 502 de Postgres).
   - ``FOREIGN_KEY_COLUMNS`` define los filtros de listado (solo FK reales).
   - ``READONLY_COLUMNS``    (``id``, ``created_at``) se remueven de payloads:
     el servidor los gestiona y no deben bloquear un PATCH que repite un GET.

3. Credenciales de lectura con permisos suficientes:
   - List/GET de DATOS PRIVADOS POR USUARIO requieren JWT
     (``get_required_authenticated_supabase``): antes un anónimo recibía
     ``200 []`` silencioso por RLS, ahora recibe un 401 explícito.
   - List/GET de CATÁLOGO usan ``get_public_read_supabase``: con JWT consultan
     como ese usuario y anónimos consultan con SERVICE ROLE, de modo que las
     políticas RLS que no incluyen a ``anon`` ya no vacían el catálogo.
   - MODO PRUEBA (``ALLOW_ANONYMOUS_LISTS=true`` en .env): anónimos pueden
     listar/CUALQUIER tabla con service role para probar todo en Insomnia;
     desactiva la variable para restaurar el 401 en tablas privadas.
   - POST/PATCH/DELETE exigen JWT: RLS sigue decidiendo fila por fila.

No existen filtros implícitos restrictivos (``published``/``status``/``hidden``)
en lectura: se devuelve lo que RLS permita ver; si un parámetro de filtro llega
``None`` no se aplica. El encadenado de postgrest-py siempre reasigna la query
(``query = query.eq(...)``) y se lee ``response.data`` (lista/dict nativo, sin
``.json()``).
"""

import inspect
import logging
import traceback
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from supabase import Client

from app.core.config import get_settings
from app.core.schema_map import (
    FOREIGN_KEY_COLUMNS,
    READONLY_COLUMNS,
    TABLE_COLUMNS,
)
from app.db.client import (
    get_public_read_supabase,
    get_required_authenticated_supabase,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@dataclass(frozen=True)
class ResourceSpec:
    """Recurso REST de una tabla física del esquema."""

    table: str
    # True: datos privados por usuario/administrativos -> la lectura exige JWT.
    private: bool = False
    # True: solo expone GET (tablas de eventos/inmutables).
    read_only: bool = False

    @property
    def filters(self) -> tuple[str, ...]:
        """Columnas filtrables: derivadas de las FK reales del esquema."""
        return FOREIGN_KEY_COLUMNS.get(self.table, ())

    @property
    def tag(self) -> str:
        return self.table.replace("_", " ").title()

    @property
    def read_db(self) -> Any:
        """Dependencia de lectura según el modo de la API.

        Con ``ALLOW_ANONYMOUS_LISTS=True`` (modo prueba), consultar sin JWT usa
        service role para TODAS las tablas. En False, solo el catálogo queda
        abierto y las tablas privadas devuelven 401 sin sesión.
        """
        if get_settings().ALLOW_ANONYMOUS_LISTS:
            return get_public_read_supabase
        return get_required_authenticated_supabase if self.private else get_public_read_supabase


# Mapeo central URL kebab-case -> tabla PostgreSQL snake_case (las 32 tablas).
RESOURCES: dict[str, ResourceSpec] = {
    "profiles": ResourceSpec("profiles", private=True),
    "user-access": ResourceSpec("user_access", private=True),
    "categories": ResourceSpec("categories"),
    "zones": ResourceSpec("zones"),
    "user-interests": ResourceSpec("user_interests", private=True),
    "businesses": ResourceSpec("businesses"),
    "places": ResourceSpec("places"),
    "place-categories": ResourceSpec("place_categories"),
    "opening-hours": ResourceSpec("opening_hours"),
    "place-media": ResourceSpec("place_media"),
    "routes": ResourceSpec("routes"),
    "route-stops": ResourceSpec("route_stops"),
    "saved-routes": ResourceSpec("saved_routes", private=True),
    "reviews": ResourceSpec("reviews"),
    "review-media": ResourceSpec("review_media"),
    "review-replies": ResourceSpec("review_replies"),
    "subscription-plans": ResourceSpec("subscription_plans"),
    "subscriptions": ResourceSpec("subscriptions", private=True),
    "offline-downloads": ResourceSpec("offline_downloads", private=True),
    "promotions": ResourceSpec("promotions"),
    "coupon-redemptions": ResourceSpec("coupon_redemptions", private=True, read_only=True),
    "experiences": ResourceSpec("experiences"),
    "reservations": ResourceSpec("reservations", private=True, read_only=True),
    "campaigns": ResourceSpec("campaigns"),
    "campaign-events": ResourceSpec("campaign_events", read_only=True),
    "place-visits": ResourceSpec("place_visits", private=True),
    "business-verifications": ResourceSpec("business_verifications", private=True),
    "tickets": ResourceSpec("tickets", private=True),
    "ticket-messages": ResourceSpec("ticket_messages", private=True),
    "notifications": ResourceSpec("notifications", private=True),
    "moderation-actions": ResourceSpec("moderation_actions", private=True),
    "audit-logs": ResourceSpec("audit_logs", private=True, read_only=True),
}

# Alias explícito de tabla física por ruta (para depuración/introspección).
TABLE_MAP: dict[str, str] = {url: spec.table for url, spec in RESOURCES.items()}


# --------------------------------------------------------------------------- #
# Errores PostgREST -> HTTP
# --------------------------------------------------------------------------- #

def _raise_database_error(exc: Exception) -> None:
    code = str(getattr(exc, "code", "") or "")
    if code == "42501":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación no autorizada por las políticas de acceso.",
        ) from exc
    if code == "23505":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El registro entra en conflicto con uno existente.",
        ) from exc
    if code in {"23503", "23514", "23502", "22P02", "22023"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Los datos no cumplen las restricciones de la base de datos.",
        ) from exc
    if code == "42703":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El cuerpo incluye campos que la tabla no reconoce.",
        ) from exc
    if code == "PGRST116":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro no encontrado.",
        ) from exc
    if code == "PGRST301":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión expiró; vuelve a iniciar sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    logger.warning("Error de Supabase al operar CRUD (%s)", code or type(exc).__name__)
    traceback.print_exc()
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="No se pudo completar la operación en la base de datos.",
    ) from exc


# --------------------------------------------------------------------------- #
# Validación de payloads contra las columnas reales de la tabla
# --------------------------------------------------------------------------- #

def _validate_payload(table: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Rechaza columnas inexistentes y remueve columnas solo de servidor."""
    columns = TABLE_COLUMNS.get(table)
    if columns is None:  # no ocurre: todas las tablas están mapeadas
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"La tabla '{table}' no está mapeada en el backend.",
        )
    unknown = sorted(set(payload) - set(columns))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"El campo '{unknown[0]}' no existe en la tabla '{table}'. "
                "Consulta /docs para los campos válidos."
            ),
        )
    return {key: value for key, value in payload.items() if key not in READONLY_COLUMNS}


# --------------------------------------------------------------------------- #
# Helpers CRUD (PostgREST: reasignar query, leer response.data, None -> skip)
# --------------------------------------------------------------------------- #

def _apply_filters(query: Any, table: str, filters: dict[str, UUID | None]) -> Any:
    fk_columns = FOREIGN_KEY_COLUMNS.get(table, ())
    for column, value in filters.items():
        if value is None:
            continue  # los parámetros opcionales no se aplican si son None
        if column not in fk_columns:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El filtro '{column}' no está disponible para esta entidad.",
            )
        query = query.eq(column, str(value))  # postgrest-py es inmutable: reasignar
    return query


def _list_records(
    table: str,
    limit: int,
    offset: int,
    filters: dict[str, UUID | None],
    db: Client,
) -> list[dict[str, Any]]:
    try:
        query = db.table(table).select("*")
        query = _apply_filters(query, table, filters)
        result = query.range(offset, offset + limit - 1).execute()
        return result.data or []
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


def _get_record(table: str, record_id: UUID, db: Client) -> dict[str, Any]:
    try:
        result = (
            db.table(table)
            .select("*")
            .eq("id", str(record_id))
            .maybe_single()
            .execute()
        )
        # Con maybe_single supabase-py devuelve None (no un objeto con .data)
        # cuando la consulta no matchea ninguna fila: getattr evita el
        # AttributeError: 'NoneType' object has no attribute 'data'.
        data = getattr(result, "data", None) if result is not None else None
        if data is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registro no encontrado.")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


def _insert_record(table: str, payload: dict[str, Any], db: Client) -> dict[str, Any]:
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El cuerpo de creación no puede estar vacío.",
        )
    clean_payload = _validate_payload(table, payload)
    if not clean_payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El cuerpo no contiene campos editables de la tabla.",
        )
    try:
        result = db.table(table).insert(clean_payload).select("*").execute()
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="La base de datos no devolvió el registro creado.",
            )
        return result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


def _update_record(table: str, record_id: UUID, payload: dict[str, Any], db: Client) -> dict[str, Any]:
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El cuerpo de actualización no puede estar vacío.",
        )
    if "id" in payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se permite cambiar el ID del registro.",
        )
    clean_payload = _validate_payload(table, payload)
    if not clean_payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El cuerpo no contiene campos editables de la tabla.",
        )
    try:
        result = (
            db.table(table)
            .update(clean_payload)
            .eq("id", str(record_id))
            .select("*")
            .maybe_single()
            .execute()
        )
        # Con maybe_single supabase-py devuelve None completo cuando el UPDATE
        # no matchea ninguna fila visible (p. ej. RLS): getattr evita el
        # AttributeError sobre 'NoneType'.
        data = getattr(result, "data", None) if result is not None else None
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registro no encontrado o no visible para este usuario.",
            )
        return data
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


def _delete_record(table: str, record_id: UUID, db: Client) -> Response:
    try:
        result = db.table(table).delete().eq("id", str(record_id)).select("id").execute()
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registro no encontrado o no visible para este usuario.",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_database_error(exc)


# --------------------------------------------------------------------------- #
# Registro automático de rutas por recurso
# --------------------------------------------------------------------------- #

def _register_list(router: APIRouter, url: str, spec: ResourceSpec) -> None:
    """GET /{recurso} con filtros = FK reales de la tabla del esquema."""
    parameters = [
        inspect.Parameter(
            "limit",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=Query(default=20, ge=1, le=100),
            annotation=int,
        ),
        inspect.Parameter(
            "offset",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=Query(default=0, ge=0),
            annotation=int,
        ),
    ]
    for column in spec.filters:
        parameters.append(
            inspect.Parameter(
                column,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Query(default=None),
                annotation=UUID | None,
            )
        )
    parameters.append(
        inspect.Parameter(
            "db",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=Depends(spec.read_db),
            annotation=Client,
        )
    )

    def list_endpoint(limit: int = 20, offset: int = 0, db: Client | None = None, **fk_filters) -> list[dict[str, Any]]:
        filters = {column: fk_filters.get(column) for column in spec.filters}
        return _list_records(spec.table, limit, offset, filters, db)  # type: ignore[arg-type]

    list_endpoint.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    list_endpoint.__name__ = f"list_{spec.table}"
    router.add_api_route(
        f"/{url}",
        list_endpoint,
        methods=["GET"],
        operation_id=f"list_{spec.table}",
        tags=[spec.tag],
        summary=f"List {spec.tag}",
        response_model=list[dict[str, Any]],
    )


def _register_get(router: APIRouter, url: str, spec: ResourceSpec) -> None:
    db_dependency = spec.read_db

    def get_endpoint(record_id: UUID, db: Client = Depends(db_dependency)) -> dict[str, Any]:
        return _get_record(spec.table, record_id, db)

    get_endpoint.__name__ = f"get_{spec.table}"
    router.add_api_route(
        f"/{url}/{{record_id}}",
        get_endpoint,
        methods=["GET"],
        operation_id=f"get_{spec.table}",
        tags=[spec.tag],
        summary=f"Get {spec.tag}",
        response_model=dict[str, Any],
    )


def _register_create(router: APIRouter, url: str, spec: ResourceSpec) -> None:
    def create_endpoint(
        payload: dict[str, Any] = Body(...),
        db: Client = Depends(get_required_authenticated_supabase),
    ) -> dict[str, Any]:
        return _insert_record(spec.table, payload, db)

    create_endpoint.__name__ = f"create_{spec.table}"
    router.add_api_route(
        f"/{url}",
        create_endpoint,
        methods=["POST"],
        operation_id=f"create_{spec.table}",
        tags=[spec.tag],
        summary=f"Create {spec.tag}",
        status_code=status.HTTP_201_CREATED,
        response_model=dict[str, Any],
    )


def _register_update(router: APIRouter, url: str, spec: ResourceSpec) -> None:
    def update_endpoint(
        record_id: UUID,
        payload: dict[str, Any] = Body(...),
        db: Client = Depends(get_required_authenticated_supabase),
    ) -> dict[str, Any]:
        return _update_record(spec.table, record_id, payload, db)

    update_endpoint.__name__ = f"update_{spec.table}"
    router.add_api_route(
        f"/{url}/{{record_id}}",
        update_endpoint,
        methods=["PATCH"],
        operation_id=f"update_{spec.table}",
        tags=[spec.tag],
        summary=f"Update {spec.tag}",
        response_model=dict[str, Any],
    )


def _register_delete(router: APIRouter, url: str, spec: ResourceSpec) -> None:
    def delete_endpoint(
        record_id: UUID,
        db: Client = Depends(get_required_authenticated_supabase),
    ) -> Response:
        return _delete_record(spec.table, record_id, db)

    delete_endpoint.__name__ = f"delete_{spec.table}"
    router.add_api_route(
        f"/{url}/{{record_id}}",
        delete_endpoint,
        methods=["DELETE"],
        operation_id=f"delete_{spec.table}",
        tags=[spec.tag],
        summary=f"Delete {spec.tag}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )


def _register_resource(router: APIRouter, url: str, spec: ResourceSpec) -> None:
    _register_list(router, url, spec)
    _register_get(router, url, spec)
    if spec.read_only:
        return
    _register_create(router, url, spec)
    _register_update(router, url, spec)
    _register_delete(router, url, spec)


for _url, _spec in RESOURCES.items():
    _register_resource(router, _url, _spec)
