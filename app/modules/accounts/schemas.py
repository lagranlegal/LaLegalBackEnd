from datetime import datetime
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
    #: Saldo calculado desde los movimientos. En una cuenta `settlement` esto
    #: es lo que te DEBEN, no lo que tienes.
    balance: Decimal
    created_at: datetime


class AccountCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: AccountType
    reference: str | None = None
    is_default: bool = False


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
