"""Job nocturno (CLAUDE.md): recalcula estados de contratos y marca
suscripciones vencidas, para todas las empresas. Corre fuera del ciclo de
request de FastAPI — invocado por un proceso programado (Fly Machine con
`schedule`, ver `fly.toml` y `docs/ARCHITECTURE.md` §11), o a mano con
`python -m app.jobs.nightly` mientras no haya scheduler configurado.

Cada paso corre en su propia transacción de bypass (`AsyncSessionLocal`
directo, no `get_tenant_db`: el job necesita ver todas las empresas) para
que una falla en un paso no revierta el otro.
"""

import asyncio
import logging

from app.core.db import AsyncSessionLocal
from app.core.logging import configure_logging
from app.modules.contracts import service as contracts_service
from app.modules.platform import service as platform_service

logger = logging.getLogger(__name__)


async def run() -> None:
    async with AsyncSessionLocal() as db, db.begin():
        contracts_updated = await contracts_service.recompute_all_statuses(db)

    async with AsyncSessionLocal() as db, db.begin():
        subscriptions_expired = await platform_service.expire_overdue_subscriptions(db)

    logger.info(
        "job_nocturno_completado: %d contrato(s) recalculado(s), %d suscripción(es) vencida(s)",
        contracts_updated,
        subscriptions_expired,
    )


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
