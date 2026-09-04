from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class CompanyCreateIn(BaseModel):
    name: str
    plan_code: str
    subscription_expires_at: date
    first_admin_email: EmailStr
    first_admin_full_name: str
    # Por defecto NO se manda correo: el enlace vuelve en la respuesta y lo
    # entrega quien está dando de alta al cliente, que es quien está hablando
    # con él en ese momento. Ver `CompanyCreatedOut.admin_invite_link`.
    send_email: bool = False


class CompanyOut(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime
    plan_code: str | None
    plan_name: str | None
    subscription_expires_at: date | None


class CompanyCreatedOut(CompanyOut):
    """La empresa recién creada, MÁS el enlace de su primer administrador.

    El alta era el único camino que dependía sí o sí del correo de Supabase:
    invitaba al primer admin con `send_email=True` y **tiraba el enlace a la
    basura**. Si ese correo no llegaba —cuota agotada, spam, o un escáner que
    lo quemó antes— el cliente nuevo se quedaba con una empresa creada y sin
    forma de entrar, y nadie podía rescatarlo salvo generándole otro enlace a
    mano desde una empresa a la que todavía no tenía acceso.

    Ahora vuelve acá. Es una credencial de un solo uso: solo la ve el
    super-admin que acaba de crear la empresa, y no se escribe en ningún log.
    """

    admin_invite_link: str | None = None


class SubscriptionExtendIn(BaseModel):
    new_expires_at: date
    notes: str | None = None
    # Opcional: el cobro es manual y fuera del sistema (CONTEXTO.md §3).
    # Registrarlo da trazabilidad básica de "quién pagó cuánto y cuándo" sin
    # construir un módulo de facturación; una extensión sin monto es válida.
    amount: Decimal | None = None


class SubscriptionEventOut(BaseModel):
    id: UUID
    event_type: str
    previous_expires_at: date | None
    new_expires_at: date | None
    amount: Decimal | None
    notes: str | None
    created_by: UUID | None
    created_at: datetime


class SubscriptionOut(BaseModel):
    id: UUID
    company_id: UUID
    plan_id: UUID
    status: str
    expires_at: date


class PlanOut(BaseModel):
    id: UUID
    name: str
    code: str
    price: Decimal | None
    modules: dict[str, bool]
    active: bool
