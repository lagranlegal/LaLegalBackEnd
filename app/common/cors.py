"""Construcción de la lista de orígenes CORS — separado de `create_app()`
para poder testear la lógica sin tocar el singleton cacheado de `Settings`
ni levantar una app FastAPI completa.
"""

# Previews de Vercel (deploy por PR/branch): dominio dinámico, solo se
# aceptan en dev — prod nunca acepta un origin que no esté en
# `cors_allow_origins` (el dominio real, vía secret por ambiente).
VERCEL_PREVIEW_REGEX = r"^https://[a-zA-Z0-9-]+\.vercel\.app$"
LOCAL_DEV_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]


def build_cors_config(*, cors_allow_origins: str, environment: str) -> tuple[list[str], str | None]:
    """`cors_allow_origins` es la lista coma-separada de `Settings` (orígenes
    exactos, p. ej. el dominio real de prod). En `environment="dev"` se
    suman los puertos locales usuales de Vite/CRA y se habilita el patrón
    de previews de Vercel; fuera de "dev" solo se acepta lo explícito.
    """
    origins = [o.strip() for o in cors_allow_origins.split(",") if o.strip()]
    origin_regex = None
    if environment == "dev":
        origins = list(dict.fromkeys(origins + LOCAL_DEV_ORIGINS))
        origin_regex = VERCEL_PREVIEW_REGEX
    return origins, origin_regex
