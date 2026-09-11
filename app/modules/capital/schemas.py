from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ContributionIn(BaseModel):
    """El dueño mete plata al negocio.

    NO es un ingreso: no se vendió nada ni se cobró un interés. Es
    patrimonio, y por eso no toca el estado de resultados — ver
    `service.create_contribution`.
    """

    account_id: UUID
    amount: Decimal = Field(gt=0)
    #: Cuándo entró la plata. Por defecto hoy; nunca futura.
    movement_date: date | None = None
    #: Opcional en el aporte y obligatorio en el retiro: meter plata al
    #: negocio se explica solo; sacarla es la decisión que alguien va a
    #: querer entender dentro de un año.
    notes: str | None = None


class WithdrawalIn(BaseModel):
    """El dueño saca plata del negocio.

    NO es un gasto: registrarlo como tal falsearía la utilidad del período
    por todo el monto retirado. Es el mismo error que este proyecto ya pagó
    tres veces ("prestar no es un gasto, cobrar no es una ganancia").
    """

    account_id: UUID
    amount: Decimal = Field(gt=0)
    movement_date: date | None = None
    #: Obligatorio. Un retiro sin motivo es la clase de línea que nadie
    #: puede explicar seis meses después, y es plata que salió del negocio.
    notes: str = Field(min_length=1)
    #: `profit` (reparto de utilidad) o `capital_return` (devolución del
    #: aporte). Contablemente NO son lo mismo; para el dueño de una
    #: compraventa la diferencia no existe hasta la declaración. Default y
    #: cero UI el día uno, igual que `extension_interest_policy` (00051).
    kind: Literal["profit", "capital_return"] = "profit"


class CapitalMovementOut(BaseModel):
    id: UUID
    number: int
    direction: Literal["contribution", "withdrawal"]
    #: `None` en un aporte. Ver `WithdrawalIn.kind`.
    kind: Literal["profit", "capital_return"] | None
    account_id: UUID
    account_name: str
    amount: Decimal
    movement_date: date
    notes: str | None
    created_at: datetime
    #: Saldo de la cuenta DESPUÉS del movimiento, para que la UI confirme el
    #: efecto sin pedir otra consulta. Mismo criterio que `TransferOut`.
    account_balance: Decimal


class CapitalPositionOut(BaseModel):
    """Lo que el dueño necesita saber ANTES de retirar.

    No bloquea nada — el proyecto ya eligió "advertir sin bloquear" en el
    LTV y en la devolución fuera de plazo. Lo que hace es contestar la
    pregunta que el dueño no puede responder de memoria: **en una
    compraventa la plata no está en el cajón, está prestada y en vitrina.**
    Retirar "lo que hay en caja" no es retirar utilidad; es descapitalizar.
    """

    from_date: date
    to_date: date
    #: Utilidad operativa del período, de `/reports/income-statement`. Es la
    #: MISMA definición (ingresos − costo de ventas − gastos), calculada por
    #: el mismo código: acá solo se trae, no se reimplementa.
    operating_profit: Decimal
    #: Aportes y retiros del período, y el neto.
    contributions: Decimal
    withdrawals: Decimal
    net_capital_movement: Decimal
    #: Dónde está realmente la plata del negocio, hoy.
    cash_and_bank: Decimal
    #: Capital prestado y todavía no recuperado (la suma de los
    #: `capital_balance` de los contratos vivos). Es plata del negocio que
    #: no está disponible.
    loan_portfolio: Decimal
    #: Inventario AL COSTO, nunca al precio de venta: contar la utilidad
    #: antes de venderla es el error clásico.
    inventory_at_cost: Decimal
    #: `cash_and_bank + loan_portfolio + inventory_at_cost`. Es lo que
    #: encoge cuando el dueño retira.
    total_capital: Decimal
    #: Cuánto se puede retirar sin tocar el capital: la utilidad del período
    #: menos lo ya retirado en él. Puede ser NEGATIVO, y ese es el aviso.
    distributable: Decimal
