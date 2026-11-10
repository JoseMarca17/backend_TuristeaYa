from fastapi import Header, HTTPException, status
from supabase import Client, create_client

from app.core.config import get_settings


def _create_client(supabase_url: str, supabase_key: str) -> Client:
    try:
        return create_client(supabase_url, supabase_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo inicializar la conexión con Supabase.",
        ) from exc


def get_supabase_anon() -> Client:
    """Crea un cliente por solicitud con la clave pública de Supabase.

    No se comparte un cliente global: el cliente autenticado modifica la cabecera
    PostgREST y compartirlo entre solicitudes podría mezclar JWT de usuarios.
    """
    settings = get_settings()
    return _create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY.get_secret_value())


def get_service_supabase() -> Client:
    """Crea un cliente con SUPABASE_SERVICE_ROLE_KEY (reporta 503 si falta).

    Solo para lecturas servidor de catálogo: el service role bypasea RLS, de modo
    que un anónimo que pregunte por el catálogo no recibe ``200 []`` cuando las
    políticas RLS no incluyen al rol ``anon``. Bajo RLS seguiría ocultando
    registros, por lo que nunca se usa para tablas de datos privados por usuario.
    """
    settings = get_settings()
    service_key = settings.SUPABASE_SERVICE_ROLE_KEY
    if service_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "La API no tiene configurado SUPABASE_SERVICE_ROLE_KEY; "
                "la lectura del catálogo requiere esa credencial."
            ),
        )
    return _create_client(settings.SUPABASE_URL, service_key.get_secret_value())


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


def get_public_read_supabase(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Client:
    """Dependencia de lectura de catálogo con credencial siempre suficiente.

    Con JWT de usuario el cliente consulta como ese usuario (RLS como siempre);
    anónimo consulta con service role para que el listado del catálogo devuelva
    los datos reales y no ``200 []`` por políticas que excluyen a ``anon``.
    """
    token = extract_bearer_token(authorization)
    if token:
        client = get_supabase_anon()
        client.postgrest.auth(token)
        return client
    return get_service_supabase()


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
