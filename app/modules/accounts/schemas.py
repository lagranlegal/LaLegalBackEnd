from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AccountType = Literal["cash", "bank", "settlement"]


class AccountOut(BaseModel):
    """Una cuenta con su saldo corriente.

    El `type` no es cosmético: decide cómo se verifica el dinero.
      · `cash`        se cuenta en el arqueo diario
      · `bank`        se concilia contra el extracto, en el ritmo del banco
      · `settlement`  es plata que TODAVÍA NO ESTÁ (Sistecrédito, datáfono):
                      alguien la debe y llegará después, y menos.
    """

    id: UUID
    name: str
    type: AccountType
    reference: str | None
    is_default: bool
    active: bool
    #: Saldo con el que la cuenta entró al sistema. Las cuentas de efectivo no
    #: lo usan: su base viene de cada sesión de caja.
    opening_balance: Decimal
    #: Saldo actual. En `cash` es lo que debería haber EN EL CAJÓN ahora (base
    #: de la sesión abierta + sus movimientos); en `bank` y `settlement` es el
    #: inicial más todo lo movido. En una `settlement` es lo que te DEBEN.
    balance: Decimal
    created_at: datetime


class AccountCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: AccountType
    reference: str | None = None
    is_default: bool = False
    #: Lo que ya había en esa cuenta antes de empezar a usar el sistema. Sin
    #: esto el saldo arrancaría en cero y quedaría negativo con el primer
    #: egreso — que fue justo el bug que motivó 00025.
    opening_balance: Decimal = Decimal("0")


class AccountUpdateIn(BaseModel):
    """El `type` NO se puede cambiar: define cómo se verifica el dinero y
    cambiarlo reinterpretaría movimientos ya registrados — una cuenta de
    efectivo que pasara a `bank` sacaría su saldo del arqueo sin que nadie
    contara nada.
    """

    name: str | None = Field(default=None, min_length=1, max_length=80)
    reference: str | None = None
    is_default: bool | None = None
    active: bool | None = None


class SettlementIn(BaseModel):
    """Liquidación de una cuenta por cobrar (Sistecrédito).

    Solo se pide lo que EFECTIVAMENTE entró y a dónde. La comisión no se
    configura ni se digita: es la diferencia contra lo que estaba por cobrar,
    así que el sistema no puede quedar desactualizado respecto al contrato.
    """

    #: Cuenta donde entró la plata — normalmente la bancaria.
    to_account_id: UUID
    #: Lo que realmente consignaron.
    amount_received: Decimal = Field(gt=0)
    #: Cuánto de lo pendiente cubre esta liquidación.
    amount_settled: Decimal = Field(gt=0)
    notes: str | None = None


class SettlementOut(BaseModel):
    settled: Decimal
    received: Decimal
    #: `settled - received`. Es lo que cobró el convenio.
    commission: Decimal
    commission_pct: Decimal | None
    new_pending_balance: Decimal


class TransferIn(BaseModel):
    """Traslado entre dos cuentas propias — típicamente consignar el efectivo
    del día en el banco.

    No es ingreso ni egreso: es la misma plata en otro bolsillo. No hay
    comisión ni monto "recibido" distinto del enviado, y ahí está la
    diferencia con una liquidación: en una liquidación llega MENOS porque el
    convenio cobra; en un traslado llega exactamente lo que salió, porque
    ambas cuentas son de la empresa.
    """

    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal = Field(gt=0)
    #: Cuándo se movió la plata. Por defecto hoy; nunca futura.
    transfer_date: date | None = None
    notes: str | None = None


class TransferOut(BaseModel):
    id: UUID
    number: int
    from_account_id: UUID
    from_account_name: str
    to_account_id: UUID
    to_account_name: str
    amount: Decimal
    transfer_date: date
    notes: str | None
    created_at: datetime
    #: Saldos DESPUÉS del traslado — para que la UI confirme el efecto sin
    #: tener que volver a pedir el listado de cuentas.
    from_balance: Decimal
    to_balance: Decimal
