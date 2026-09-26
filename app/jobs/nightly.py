"""Job nocturno (CLAUDE.md): recalcula estados de contratos y marca
suscripciones vencidas, para todas las empresas. Corre fuera del ciclo de
request de FastAPI — invocado por un proceso programado (Fly Machine con
`schedule`, ver `fly.toml` y `docs/ARCHITECTURE.md` §11), o a mano con
`python -m app.jobs.nightly` mientras no haya scheduler configurado.

Cada paso corre en su propia transacción de bypass (`AsyncSessionLocal`
directo, no `get_tenant_db`: el job necesita ver todas las empresas) para
que una falla en un paso no revierta el otro.

Pasos 3, 4 y 5 (docs/NOTIFICACIONES.md §5.2, §20): el resumen a la empresa,
los recordatorios al cliente (R1–R4) y el despacho de correos. El 3 y el 4 van
DESPUÉS de `recompute_all_statuses` a propósito: "entró en mora" se lee del
estado que el paso 1 acaba de persistir. Y los dos van ANTES del despacho, que
manda lo que ellos acaban de crear.
Ninguno de los dos puede tumbar el job: una empresa o una entrega que falla se
registra y se sigue, y sin `RESEND_API_KEY` las entregas quedan
`skipped_no_provider` en vez de fallar.
"""

import asyncio
import logging
from datetime import UTC, datetime

from app.core.db import AsyncSessionLocal
from app.core.logging import configure_logging
from app.modules.contracts import service as contracts_service
from app.modules.notifications import digest as notifications_digest
from app.modules.notifications import dispatcher as notifications_dispatcher
from app.modules.notifications import reminders as notifications_reminders
from app.modules.notifications.providers import EmailProvider, get_default_provider
from app.modules.platform import service as platform_service

logger = logging.getLogger(__name__)


async def run(*, now: datetime | None = None, provider: EmailProvider | None = None) -> None:
    """`now` y `provider` son inyectables para los tests (un instante fijo y un
    proveedor que no manda nada de verdad); en producción valen el reloj real
    y Resend, o el proveedor nulo si no hay key."""
    async with AsyncSessionLocal() as db, db.begin():
        contracts_updated = await contracts_service.recompute_all_statuses(db)

    async with AsyncSessionLocal() as db, db.begin():
        subscriptions_expired = await platform_service.expire_overdue_subscriptions(db)

    digests = await notifications_digest.build_all_digests(now=now or datetime.now(UTC))
    reminders = await notifications_reminders.build_all_reminders(now=now or datetime.now(UTC))
    # Sin `now` inyectado, el despachador toma su propio reloj DESPUÉS de los
    # pasos 3 y 4: las entregas que ese paso acaba de crear nacen con
    # `scheduled_at = now()` de la base, y un reloj tomado antes las dejaría
    # para mañana.
    dispatched = await notifications_dispatcher.dispatch_due(
        provider=provider or get_default_provider(), now=now
    )

    logger.info(
        "job_nocturno_completado: %d contrato(s) recalculado(s), %d suscripción(es) vencida(s); "
        "resumen: %d empresa(s), %d diario(s) con contenido, %d vacío(s), %d semanal(es), "
        "%d con error; recordatorios: %d evento(s) nuevo(s) en %d empresa(s), %d con error "
        "%s; entregas: %s",
        contracts_updated,
        subscriptions_expired,
        digests.companies,
        digests.daily_sent,
        digests.daily_empty,
        digests.weekly,
        digests.errors,
        reminders.events,
        reminders.companies,
        reminders.errors,
        dict(sorted(reminders.deliveries.items())),
        dict(sorted(dispatched.by_status.items())),
    )


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
