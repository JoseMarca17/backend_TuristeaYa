"""Subida controlada de imágenes a Supabase Storage."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from supabase import Client

from app.core.config import get_settings
from app.db.client import extract_bearer_token, get_required_authenticated_supabase, get_service_supabase

router = APIRouter()
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
CHUNK_SIZE = 1024 * 1024


def _user_id(db: Client, authorization: str | None) -> str:
    token = extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Se requiere autenticación.")
    try:
        user = db.auth.get_user(token).user
        if user is None:
            raise ValueError("missing user")
        return str(user.id)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="La sesión no es válida.") from exc


def _is_admin(db: Client, user_id: str) -> bool:
    rows = db.table("user_access").select("role,status").eq("user_id", user_id).eq("status", "active").execute().data or []
    return any(row.get("role") == "admin" for row in rows)


def _can_upload_review(db: Client, review_id: UUID, user_id: str) -> None:
    review = db.table("reviews").select("user_id").eq("id", str(review_id)).maybe_single().execute()
    data = getattr(review, "data", None) if review is not None else None
    if data is None:
        raise HTTPException(status_code=404, detail="La reseña no existe.")
    if str(data.get("user_id")) != user_id and not _is_admin(db, user_id):
        raise HTTPException(status_code=403, detail="Solo el autor puede adjuntar medios a esta reseña.")


def _can_upload_place(db: Client, place_id: UUID, user_id: str) -> None:
    place = db.table("places").select("business_id").eq("id", str(place_id)).maybe_single().execute()
    place_data = getattr(place, "data", None) if place is not None else None
    if place_data is None:
        raise HTTPException(status_code=404, detail="El lugar no existe.")
    if _is_admin(db, user_id):
        return
    business_id = place_data.get("business_id")
    if not business_id:
        raise HTTPException(status_code=403, detail="Solo el administrador puede adjuntar medios a este lugar.")
    business = db.table("businesses").select("owner_id").eq("id", str(business_id)).maybe_single().execute()
    business_data = getattr(business, "data", None) if business is not None else None
    if business_data is None or str(business_data.get("owner_id")) != user_id:
        raise HTTPException(status_code=403, detail="Solo el propietario del negocio puede adjuntar medios a este lugar.")


async def _read_image(file: UploadFile) -> tuple[bytes, str]:
    content_type = (file.content_type or "").lower()
    extension = ALLOWED_TYPES.get(content_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="Solo se aceptan imágenes JPG, PNG o WEBP.")
    settings = get_settings()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.MEDIA_MAX_BYTES:
            raise HTTPException(status_code=413, detail="La imagen supera el tamaño máximo permitido.")
        chunks.append(chunk)
    if not total:
        raise HTTPException(status_code=422, detail="La imagen está vacía.")
    return b"".join(chunks), extension


def _signed_url(storage: Any, path: str) -> str | None:
    response = storage.from_(get_settings().SUPABASE_MEDIA_BUCKET).create_signed_url(path, 3600)
    return response.get("signedURL") or response.get("signedUrl") if isinstance(response, dict) else None


async def _upload(
    *,
    table: str,
    foreign_key: str,
    record_id: UUID,
    file: UploadFile,
    db: Client,
    authorization: str | None,
) -> dict[str, Any]:
    user_id = _user_id(db, authorization)
    if table == "review_media":
        _can_upload_review(db, record_id, user_id)
        folder = "reviews"
    else:
        _can_upload_place(db, record_id, user_id)
        folder = "places"
    content, extension = await _read_image(file)
    path = str(PurePosixPath(folder) / str(record_id) / f"{uuid4().hex}{extension}")
    service = get_service_supabase()
    storage = service.storage.from_(get_settings().SUPABASE_MEDIA_BUCKET)
    try:
        storage.upload(path, content, {"content-type": file.content_type or "application/octet-stream", "upsert": False})
        result = db.table(table).insert({foreign_key: str(record_id), "storage_path": path}).execute()
        data = result.data[0] if result.data else None
        if data is None:
            raise RuntimeError("La base de datos no devolvió el medio creado.")
        return {**data, "url": _signed_url(service.storage, path)}
    except HTTPException:
        raise
    except Exception as exc:
        try:
            storage.remove([path])
        except Exception:
            pass
        raise HTTPException(status_code=502, detail="No se pudo guardar la imagen.") from exc


@router.post("/media/reviews/{review_id}", status_code=status.HTTP_201_CREATED, summary="Subir imagen de una reseña")
async def upload_review_media(
    review_id: UUID,
    file: UploadFile = File(...),
    db: Client = Depends(get_required_authenticated_supabase),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    return await _upload(table="review_media", foreign_key="review_id", record_id=review_id, file=file, db=db, authorization=authorization)


@router.post("/media/places/{place_id}", status_code=status.HTTP_201_CREATED, summary="Subir imagen de un lugar")
async def upload_place_media(
    place_id: UUID,
    file: UploadFile = File(...),
    db: Client = Depends(get_required_authenticated_supabase),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    return await _upload(table="place_media", foreign_key="place_id", record_id=place_id, file=file, db=db, authorization=authorization)
