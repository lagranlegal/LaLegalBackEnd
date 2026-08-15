"""Función de integración que otros módulos usan para saber "qué día es
hoy" para una empresa (CLAUDE.md regla 2 — nunca importar `platform.service`
desde otro módulo, solo esto).
"""

from datetime import date
from uuid import UUID

from cachetools import TTLCache
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.tenant_time import today_in
from app.modules.platform import repository

# Cache corto: la zona horaria de una empresa casi nunca cambia, pero se
# consulta en cada operación de negocio con fecha (contratos, caja).
_timezone_cache: TTLCache[UUID, str] = TTLCache(maxsize=1024, ttl=300)


async def get_company_timezone(db: AsyncSession, *, company_id: UUID) -> str:
    tz_name = _timezone_cache.get(company_id)
    if tz_name is None:
        tz_name = await repository.get_company_timezone(db, company_id=company_id)
        _timezone_cache[company_id] = tz_name
    return tz_name


async def get_company_today(db: AsyncSession, *, company_id: UUID) -> date:
    tz_name = await get_company_timezone(db, company_id=company_id)
    return today_in(tz_name)
