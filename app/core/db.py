import json
from collections.abc import AsyncGenerator, Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.settings import get_settings

# NullPool + statement_cache_size=0: obligatorio para que asyncpg no reutilice
# prepared statements bajo un pooler en modo transacción (Supavisor / pgbouncer).
# Ver CLAUDE.md regla 1: la conexión va por Supavisor en modo transacción.
engine = create_async_engine(
    get_settings().database_url,
    poolclass=NullPool,
    connect_args={"statement_cache_size": 0},
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Sesión con una transacción explícita, sin claims de tenant fijados.

    Úsese directamente solo para operaciones de plataforma (bypass RLS,
    fuera del alcance de este esqueleto). Los endpoints de negocio deben
    depender de `app.core.security.get_tenant_db`.
    """
    async with AsyncSessionLocal() as session, session.begin():
        yield session


async def apply_tenant_claims(session: AsyncSession, claims: Mapping[str, Any]) -> None:
    """Fija el tenant de la transacción actual (regla 1 de CLAUDE.md).

    `SET LOCAL ROLE authenticated` es lo que hace que RLS se aplique de
    verdad: un rol superusuario (p. ej. `postgres` en local) siempre
    bypassea RLS, sin importar los claims. Cambiando el rol efectivo de la
    transacción a `authenticated` (no-superusuario), Postgres sí evalúa las
    políticas — igual en local que en producción, donde el rol de conexión
    deberá tener `GRANT authenticated TO <rol>`.
    """
    await session.execute(text("SET LOCAL ROLE authenticated"))
    await session.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": json.dumps(dict(claims))},
    )
