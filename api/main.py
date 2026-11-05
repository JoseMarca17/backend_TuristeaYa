from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import actions, auth, crud

settings = get_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description=(
        "API REST de TuristeaYa para autenticación, catálogo turístico, "
        "rutas, promociones y reservas. Supabase RLS aplica los permisos "
        "de cada usuario autenticado."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Authorization se envía explícitamente como cabecera. No se usan cookies.
    allow_credentials=False,
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX, tags=["Autenticación"])
app.include_router(actions.router, prefix=settings.API_V1_PREFIX, tags=["Operaciones"])
app.include_router(crud.router, prefix=settings.API_V1_PREFIX, tags=["Recursos"])


@app.get("/health", tags=["Health"], summary="Estado de la API")
def health_check() -> dict[str, str]:
    return {"status": "ok", "app": "TuristeaYa"}
