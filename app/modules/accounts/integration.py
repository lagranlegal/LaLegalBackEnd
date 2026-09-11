"""Funciones de integración mínimas de `accounts` para otros módulos
(CLAUDE.md regla 2 — un módulo nunca importa el `service.py` de otro).

`sales` las necesita para decidir si una devolución en efectivo es segura:
si la venta original se cobró por una cuenta `settlement` (Sistecrédito) que
todavía no se liquidó, no hay plata real que devolver — devolverla en
efectivo sacaría dinero que el negocio nunca recibió.

`capital` (00054) las necesita para dos cosas: nombrar la cuenta en el
documento del aporte o del retiro, y responder cuánta plata LÍQUIDA tiene el
negocio antes de que el dueño retire.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts import repository


@dataclass(frozen=True)
class AccountSummary:
    """Lo mínimo que otro módulo necesita saber de una cuenta: cómo se llama
    y de qué tipo es. Una sola consulta en vez de dos — pedir el tipo y el
    nombre por separado eran dos viajes para la misma fila."""

    name: str
    type: str


async def get_account_type(db: AsyncSession, *, company_id: UUID, account_id: UUID) -> str | None:
    row = await repository.get_account(db, company_id=company_id, account_id=account_id)
    return str(row._mapping["type"]) if row is not None else None


async def get_account_balance(db: AsyncSession, *, company_id: UUID, account_id: UUID) -> Decimal:
    return await repository.account_balance(db, company_id=company_id, account_id=account_id)


async def get_cash_on_hand(db: AsyncSession, *, company_id: UUID) -> Decimal:
    """Todo el efectivo que el sistema cree que hay en cajones, ahora mismo.

    Es contra este número que se arquea al abrir y al cerrar el turno, y por
    eso suma TODAS las cuentas `cash` y no solo la predeterminada: es el
    mismo criterio con el que `cashbox._expected_cash` decide qué entra al
    arqueo (el tipo de cuenta, no el medio de pago). Si los dos no sumaran lo
    mismo, un descuadre podría aparecer y desaparecer según por dónde se
    mirara.

    Desde 00048 esto es una suma de movimientos y ya no depende de que haya
    una sesión abierta: el efectivo del cajón sigue existiendo a las 11 de la
    noche.
    """
    rows = await repository.list_accounts(db, company_id=company_id, include_inactive=True)
    return sum(
        (Decimal(str(r._mapping["balance"])) for r in rows if r._mapping["type"] == "cash"),
        Decimal("0.00"),
    )


async def get_account_summary(
    db: AsyncSession, *, company_id: UUID, account_id: UUID
) -> AccountSummary | None:
    row = await repository.get_account(db, company_id=company_id, account_id=account_id)
    if row is None:
        return None
    return AccountSummary(name=str(row._mapping["name"]), type=str(row._mapping["type"]))


async def get_liquid_capital(db: AsyncSession, *, company_id: UUID) -> Decimal:
    """Toda la plata del negocio que ESTÁ, sumando cajones, bóvedas y bancos.

    Deja fuera las cuentas `settlement` a propósito: *"una cuenta por cobrar
    no es plata"*. Sumarlas acá haría creer que hay más de lo que hay, justo
    en la pantalla donde eso más duele — la que el dueño mira antes de sacar
    dinero del negocio.

    Una `vault` SÍ entra: es efectivo real, solo que no es un punto de cobro.
    El filtro va por TIPO DE CUENTA, que es lo que decide qué clase de plata
    es cada saldo.
    """
    rows = await repository.list_accounts(db, company_id=company_id, include_inactive=True)
    return sum(
        (
            Decimal(str(r._mapping["balance"]))
            for r in rows
            if r._mapping["type"] in ("cash", "bank", "vault")
        ),
        Decimal("0.00"),
    )
