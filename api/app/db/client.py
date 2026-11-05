from fastapi import Header, HTTPException, status
from supabase import Client, create_client

from app.core.config import get_settings


def get_supabase_anon() -> Client:
    """Crea un cliente por solicitud con la clave pública de Supabase.

    No se comparte un cliente global: el cliente autenticado modifica la cabecera
    PostgREST y compartirlo entre solicitudes podría mezclar JWT de usuarios.
    """
    settings = get_settings()
    try:
        return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY.get_secret_value())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo inicializar la conexión con Supabase.",
        ) from exc


def extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None

    scheme, separator, token = authorization.strip().partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El encabezado Authorization debe usar el esquema Bearer.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def get_authenticated_supabase(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Client:
    """Devuelve un cliente con JWT para que Postgres evalúe las políticas RLS.

    Sin Authorization el cliente permanece anónimo para permitir lecturas públicas.
    Los endpoints que exigen sesión validan el JWT de forma explícita.
    """
    client = get_supabase_anon()
    token = extract_bearer_token(authorization)
    if token:
        client.postgrest.auth(token)
    return client


def get_required_authenticated_supabase(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Client:
    """Dependencia para acciones que siempre requieren una sesión válida."""
    token = extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    client = get_supabase_anon()
    client.postgrest.auth(token)
    return client
