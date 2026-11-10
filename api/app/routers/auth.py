import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from supabase import Client

from app.core.config import get_settings
from app.db.client import (
    extract_bearer_token,
    get_authenticated_supabase,
    get_supabase_anon,
)
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if hasattr(value, "dict"):
        return value.dict(exclude_none=True)
    if isinstance(value, dict):
        return value
    return {"id": str(value)}


def _token_response(session: Any, user: Any) -> TokenResponse:
    access_token = getattr(session, "access_token", None)
    refresh_token = getattr(session, "refresh_token", None)
    if not access_token or not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Supabase no devolvió una sesión completa.",
        )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=_as_dict(user),
    )


def _persist_accepted_terms(db: Client, session: Any, user: Any, accepted_at: str | None) -> None:
    """Persiste la aceptación cuando hay JWT, siempre sujeto a las políticas RLS."""
    if not accepted_at or user is None:
        return
    try:
        db.postgrest.auth(session.access_token)
        db.table("profiles").update({"terms_accepted_at": accepted_at}).eq(
            "id", str(user.id)
        ).execute()
    except Exception as exc:
        # Auth ya pudo completar el registro/login; no se ocultan fallos de sesión.
        logger.warning("No se pudo sincronizar terms_accepted_at (%s)", type(exc).__name__)


def _auth_error_message(exc: Exception) -> str:
    """Devuelve mensajes conocidos de Auth sin reenviar detalles internos."""
    message = str(getattr(exc, "message", "") or "").lower()
    if "already registered" in message or "already been registered" in message:
        return "Ya existe una cuenta con ese correo electrónico."
    if "password" in message and ("weak" in message or "short" in message):
        return "La contraseña no cumple los requisitos de seguridad."
    if "email" in message and ("invalid" in message or "not valid" in message):
        return "El correo electrónico no es válido."
    return "No se pudo completar la operación de autenticación. Verifica los datos e inténtalo de nuevo."


@router.post(
    "/auth/register",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses={
        202: {"description": "Cuenta creada; Supabase requiere confirmar el correo."},
        400: {"description": "Datos inválidos o cuenta existente."},
    },
    summary="Register",
    description="Registrar una cuenta de usuario en Supabase Auth.",
)
def register(
    payload: RegisterRequest,
    db: Client = Depends(get_supabase_anon),
) -> TokenResponse | JSONResponse:
    if not payload.accept_terms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes aceptar los términos para crear una cuenta.",
        )

    accepted_at = datetime.now(timezone.utc).isoformat()
    try:
        result = db.auth.sign_up(
            {
                "email": str(payload.email),
                "password": payload.password,
                "options": {
                    "data": {
                        "full_name": payload.full_name,
                        "accept_terms": True,
                        "terms_accepted_at": accepted_at,
                    }
                },
            }
        )
    except Exception as exc:
        logger.info("Supabase rechazó el registro: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_auth_error_message(exc),
        ) from exc

    user = getattr(result, "user", None)
    session = getattr(result, "session", None)
    if session is None:
        # Supabase no emite un JWT hasta que se confirme el correo. Los metadatos
        # guardan la aceptación; el trigger SQL actual solo copia full_name a profiles.
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "message": "Cuenta creada. Revisa tu correo para confirmar la cuenta.",
                "user": _as_dict(user),
            },
        )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Supabase creó la sesión pero no devolvió los datos de usuario.",
        )

    # Con confirmación desactivada el trigger ya creó el perfil. Si la cuenta
    # requiere confirmación, el login posterior sincroniza esta misma metadata.
    _persist_accepted_terms(db, session, user, accepted_at)
    return _token_response(session, user)


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Login",
    description="Iniciar sesión con correo y contraseña.",
)
def login(payload: LoginRequest, db: Client = Depends(get_supabase_anon)) -> TokenResponse:
    try:
        result = db.auth.sign_in_with_password(
            {"email": str(payload.email), "password": payload.password}
        )
    except Exception as exc:
        logger.info("Fallo de autenticación de usuario (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos, o la cuenta requiere confirmación.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    session = getattr(result, "session", None)
    user = getattr(result, "user", None)
    if session is None or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase no devolvió una sesión válida.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_metadata = getattr(user, "user_metadata", None) or {}
    if isinstance(user_metadata, dict) and user_metadata.get("accept_terms") is True:
        _persist_accepted_terms(
            db,
            session,
            user,
            user_metadata.get("terms_accepted_at"),
        )
    return _token_response(session, user)


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    summary="Refresh",
    description="Renovar una sesión con el refresh token.",
)
def refresh_session(
    payload: RefreshRequest,
    db: Client = Depends(get_supabase_anon),
) -> TokenResponse:
    try:
        result = db.auth.refresh_session(payload.refresh_token)
    except Exception as exc:
        logger.info("No se pudo renovar una sesión (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El refresh token es inválido o expiró. Inicia sesión nuevamente.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    session = getattr(result, "session", None)
    user = getattr(result, "user", None)
    if session is None or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase no devolvió una sesión renovada válida.",
        )
    return _token_response(session, user)


def _revoke_access_token(access_token: str) -> None:
    """Cierra una sesión stateless cuando el cliente no envía refresh token.

    El endpoint Auth logout de Supabase acepta el JWT de acceso. La llamada se
    limita a Auth; las operaciones de base de datos siguen usando supabase-py.
    """
    settings = get_settings()
    try:
        response = httpx.post(
            f"{settings.SUPABASE_URL}/auth/v1/logout",
            headers={
                "apikey": settings.SUPABASE_KEY.get_secret_value(),
                "Authorization": f"Bearer {access_token}",
            },
            timeout=10.0,
        )
        if response.status_code not in (200, 204):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No se pudo cerrar la sesión; el token puede haber expirado.",
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de autenticación no está disponible.",
        ) from exc


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Logout",
    description="Cerrar sesión revocando el token enviado en Authorization.",
)
def logout(
    payload: LogoutRequest | None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Client = Depends(get_authenticated_supabase),
) -> Response:
    access_token = extract_bearer_token(authorization)
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere un token Bearer para cerrar sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload and payload.refresh_token:
        try:
            db.auth.set_session(access_token, payload.refresh_token)
            db.auth.sign_out()
        except Exception as exc:
            logger.info("El SDK no pudo cerrar la sesión (%s)", type(exc).__name__)
            _revoke_access_token(access_token)
    else:
        # En una API stateless el cliente Auth no comparte el almacenamiento de
        # sesión de la app móvil, por eso se revoca el JWT enviado en Authorization.
        _revoke_access_token(access_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    summary="Me",
    description="Obtener el perfil autenticado a partir del JWT de Supabase.",
)
def get_me(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Client = Depends(get_authenticated_supabase),
) -> dict[str, Any]:
    access_token = extract_bearer_token(authorization)
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        auth_response = db.auth.get_user(access_token)
        user = getattr(auth_response, "user", None)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido.")
        profile_response = (
            db.table("profiles").select("*").eq("id", str(user.id)).maybe_single().execute()
        )
        profile_data = (
            getattr(profile_response, "data", None) if profile_response is not None else None
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.info("No se pudo cargar el perfil (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión no es válida o no tiene acceso al perfil.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if profile_data is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El perfil no está disponible o la cuenta no está activa.",
        )
    return profile_data
