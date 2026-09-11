"""El dinero del DUEÑO: aportes al negocio y retiros de utilidad (`00054`).

**Ni un aporte es un ingreso, ni un retiro es un gasto.** Los dos mueven el
patrimonio, no el resultado del período. Es la única regla de fondo de este
módulo, y la que un sistema contable expresaría con `Débito Caja / Crédito
Patrimonio`.

**Y esta app no necesita partida doble para cumplirla.**
`reports.get_income_statement` lee DOCUMENTOS (`sale`, `contract_payment`,
`expense`), nunca `cash_movement`. Un `capital_movement` no es ninguno de
esos tres, así que queda fuera del estado de resultados por construcción —
sin una línea de exclusión que alguien pueda olvidar. El modelo ya protegía
esto antes de que el caso existiera.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_date_page
from app.core.errors import AppError, NotFoundError
from app.modules.accounts import integration as accounts_integration
from app.modules.capital import repository
from app.modules.capital.schemas import (
    CapitalMovementOut,
    CapitalPositionOut,
    ContributionIn,
    WithdrawalIn,
)
from app.modules.cashbox import integration as cashbox_integration
from app.modules.identity import repository as identity_repo
from app.modules.platform import integration as platform_integration
from app.modules.reports import integration as reports_integration


def _row_to_movement(row: Row[Any], balance: Decimal) -> CapitalMovementOut:
    m = row._mapping
    return CapitalMovementOut(
        id=m["id"],
        number=m["number"],
        direction=m["direction"],
        kind=m["kind"],
        account_id=m["account_id"],
        account_name=m["account_name"],
        amount=m["amount"],
        movement_date=m["movement_date"],
        notes=m["notes"],
        created_at=m["created_at"],
        account_balance=balance,
    )


async def _validar_cuenta(
    db: AsyncSession, *, company_id: UUID, account_id: UUID
) -> accounts_integration.AccountSummary:
    cuenta = await accounts_integration.get_account_summary(
        db, company_id=company_id, account_id=account_id
    )
    if cuenta is None:
        raise NotFoundError("La cuenta indicada no existe en esta empresa.")
    if cuenta.type == "settlement":
        # Una cuenta por cobrar representa plata que alguien te DEBE. No se
        # puede meter en ella el efectivo del bolsillo del dueño ni sacar de
        # ella un retiro: el saldo no existe todavía. Mismo criterio que
        # `resolve_account_for_movement` con las salidas.
        raise AppError(
            "Una cuenta por cobrar no sirve para esto: representa plata que "
            "todavía te deben, no un saldo del que se pueda meter o sacar "
            "dinero. Elige la cuenta real.",
            details={"account_id": str(account_id)},
            code="ACCOUNT_CANNOT_FUND_PAYMENT",
        )
    return cuenta


async def _fecha_del_documento(db: AsyncSession, *, company_id: UUID, pedida: date | None) -> date:
    """Nunca futura, y contra el hoy de la EMPRESA.

    `current_date` de Postgres es UTC: entre las 7pm y medianoche de Bogotá ya
    es el día siguiente, y una fecha "de hoy" se rechazaría por futura. Este
    proyecto ya se comió ese bug dos veces.
    """
    hoy = await platform_integration.get_company_today(db, company_id=company_id)
    fecha = pedida or hoy
    if fecha > hoy:
        raise AppError(
            "La fecha no puede estar en el futuro.",
            details={"movement_date": str(fecha), "today": str(hoy)},
        )
    return fecha


async def _registrar(
    db: AsyncSession,
    *,
    company_id: UUID,
    direction: str,
    kind: str | None,
    account_id: UUID,
    amount: Decimal,
    movement_date: date | None,
    notes: str | None,
    actor_id: UUID,
    idempotency_key: str,
) -> CapitalMovementOut:
    """El camino común del aporte y del retiro.

    Son el mismo documento en dos sentidos —igual que un traslado es una
    salida y una entrada—, así que la validación, el consecutivo, la
    idempotencia, el movimiento de caja y la auditoría se escriben UNA vez.
    Lo único que cambia es la dirección, el concepto y qué se valida antes.

    Todo en UNA transacción (CLAUDE.md regla 4).
    """
    existente = await repository.find_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existente is not None:
        return await get_movement(db, company_id=company_id, movement_id=existente._mapping["id"])

    cuenta = await _validar_cuenta(db, company_id=company_id, account_id=account_id)
    fecha = await _fecha_del_documento(db, company_id=company_id, pedida=movement_date)

    # La sesión de caja la exige el TIPO DE CUENTA, no la operación — y esa
    # regla vive en un solo lugar a propósito (`cashbox.integration`). Meter o
    # sacar billetes de un cajón cerrado no se puede; una transferencia del
    # dueño a la cuenta del banco, sí, a cualquier hora.
    resuelta = await cashbox_integration.resolve_account_for_movement(
        db,
        company_id=company_id,
        payment_method="cash" if cuenta.type == "cash" else "transfer",
        account_id=account_id,
        direction="out" if direction == "withdrawal" else "in",
    )

    # El retiro no puede sacar de una cuenta más de lo que tiene. Acá SÍ se
    # valida —a diferencia del desembolso de un préstamo, que sigue sin
    # hacerlo (ver DECISIONES_PENDIENTES §3)— porque el argumento que sostiene
    # aquella excepción no aplica: un préstamo se puede registrar fuera de
    # orden en un mostrador con movimiento; un retiro del dueño es un acto
    # deliberado, y sacar plata que no está es un descuadre fabricado.
    if direction == "withdrawal":
        saldo = await accounts_integration.get_account_balance(
            db, company_id=company_id, account_id=account_id
        )
        if amount > saldo:
            raise AppError(
                "No se puede retirar más de lo que hay en la cuenta.",
                details={"disponible": str(saldo), "amount": str(amount)},
            )

    movement_id = uuid4()
    number = await repository.next_number(db, company_id=company_id)
    await repository.insert_movement(
        db,
        movement_id=movement_id,
        company_id=company_id,
        number=number,
        direction=direction,
        kind=kind,
        account_id=account_id,
        amount=amount,
        movement_date=fecha,
        notes=notes,
        created_by=actor_id,
        idempotency_key=idempotency_key,
    )

    await cashbox_integration.record_movement(
        db,
        session_id=resuelta.session_id,
        company_id=company_id,
        module="general",
        direction="in" if direction == "contribution" else "out",
        # Conceptos PROPIOS y no `adjustment` ni `expense`: un ajuste
        # significa "el sistema no cuadra con la realidad", y acá cuadra
        # perfecto; y un gasto falsearía la utilidad por todo el monto. Mismo
        # argumento que usó 00032 con los traslados.
        concept="owner_contribution" if direction == "contribution" else "owner_withdrawal",
        amount=amount,
        payment_method="cash" if cuenta.type == "cash" else "transfer",
        reference_type="capital_movement",
        reference_id=movement_id,
        created_by=actor_id,
        notes=notes,
        account_id=account_id,
    )

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="capital",
        action=direction,
        entity_type="capital_movement",
        entity_id=movement_id,
        before=None,
        after={
            "number": str(number),
            "direction": direction,
            "kind": str(kind) if kind else "",
            "amount": str(amount),
            "account": cuenta.name,
            "movement_date": str(fecha),
            "notes": notes or "",
        },
    )
    return await get_movement(db, company_id=company_id, movement_id=movement_id)


async def create_contribution(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: ContributionIn,
    actor_id: UUID,
    idempotency_key: str,
) -> CapitalMovementOut:
    """El dueño mete plata al negocio.

    Hasta hoy esto no se podía registrar, y las tres salidas que quedaban
    estaban mal: un `adjustment` de arqueo (que miente — el sistema sí
    cuadraba), un traslado (que solo sirve si la plata ya está en una cuenta
    de la empresa) o nada, que deja plata en el cajón sin documento.
    """
    return await _registrar(
        db,
        company_id=company_id,
        direction="contribution",
        kind=None,
        account_id=body.account_id,
        amount=body.amount,
        movement_date=body.movement_date,
        notes=body.notes,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )


async def create_withdrawal(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: WithdrawalIn,
    actor_id: UUID,
    idempotency_key: str,
) -> CapitalMovementOut:
    """El dueño saca plata del negocio.

    **No bloquea si no hay utilidad.** El dueño puede retirar su propio
    capital y está en su derecho; lo que la app hace es decirle qué está
    haciendo, con `GET /capital/position` antes de confirmar. Es el mismo
    criterio que el proyecto ya eligió para el LTV y para el plazo de
    devolución: advertir sin estorbar.
    """
    return await _registrar(
        db,
        company_id=company_id,
        direction="withdrawal",
        kind=body.kind,
        account_id=body.account_id,
        amount=body.amount,
        movement_date=body.movement_date,
        notes=body.notes,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )


async def get_movement(
    db: AsyncSession, *, company_id: UUID, movement_id: UUID
) -> CapitalMovementOut:
    row = await repository.get_movement(db, company_id=company_id, movement_id=movement_id)
    if row is None:
        raise NotFoundError("El movimiento de capital no existe en esta empresa.")
    saldo = await accounts_integration.get_account_balance(
        db, company_id=company_id, account_id=row._mapping["account_id"]
    )
    return _row_to_movement(row, saldo)


async def list_movements(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: tuple[date, UUID] | None,
    limit: int,
    direction: str | None,
) -> CursorPage[CapitalMovementOut]:
    rows = await repository.list_movements(
        db, company_id=company_id, cursor=cursor, limit=limit, direction=direction
    )
    # Los saldos se resuelven una sola vez por cuenta: `account_balance`
    # recalcula el listado entero de cuentas en cada llamada, así que pedirlo
    # por fila sería cuadrático sobre una página.
    saldos: dict[UUID, Decimal] = {}
    items: list[CapitalMovementOut] = []
    for row in rows:
        account_id = row._mapping["account_id"]
        if account_id not in saldos:
            saldos[account_id] = await accounts_integration.get_account_balance(
                db, company_id=company_id, account_id=account_id
            )
        items.append(_row_to_movement(row, saldos[account_id]))
    return make_date_page(items, limit, lambda item: (item.movement_date, item.id))


async def get_position(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> CapitalPositionOut:
    """Lo que el dueño necesita ver ANTES de retirar.

    La pregunta que contesta no es "¿cuánto hay en la caja?" sino **"¿dónde
    está la plata del negocio?"**. En una compraventa la mayor parte no está
    en el cajón: está prestada y en vitrina. Retirar "lo que hay en caja" no
    es retirar utilidad — es descapitalizar, y es exactamente el error que
    este módulo existe para hacer visible.

    `distributable` puede salir NEGATIVO a propósito. Un retiro mayor a la
    utilidad del período es una devolución de capital, se llame como se
    llame, y ese número es el aviso.
    """
    utilidad = await reports_integration.get_operating_profit(
        db, company_id=company_id, from_date=from_date, to_date=to_date
    )
    totales = await repository.totals_in_period(
        db, company_id=company_id, from_date=from_date, to_date=to_date
    )
    aportes = Decimal(str(totales._mapping["contributions"]))
    retiros = Decimal(str(totales._mapping["withdrawals"]))

    # Solo lo que es plata de verdad y disponible: cajones, bóvedas y bancos.
    # Las cuentas por cobrar quedan fuera — "una cuenta por cobrar no es
    # plata" —, y el filtro por TIPO vive en `accounts` porque es su regla.
    disponible = await accounts_integration.get_liquid_capital(db, company_id=company_id)
    cartera = await repository.loan_portfolio(db, company_id=company_id)
    inventario = await repository.inventory_at_cost(db, company_id=company_id)

    return CapitalPositionOut(
        from_date=from_date,
        to_date=to_date,
        operating_profit=utilidad,
        contributions=aportes,
        withdrawals=retiros,
        net_capital_movement=aportes - retiros,
        cash_and_bank=disponible,
        loan_portfolio=cartera,
        inventory_at_cost=inventario,
        total_capital=disponible + cartera + inventario,
        distributable=utilidad - retiros,
    )
