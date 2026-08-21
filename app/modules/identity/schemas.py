from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserOut(BaseModel):
    id: UUID
    full_name: str
    email: str
    role_id: UUID
    status: str
    created_at: datetime


class InviteUserIn(BaseModel):
    email: EmailStr
    full_name: str
    role_id: UUID
    #: `False` entrega un enlace en la respuesta en vez de mandar el correo.
    #: Sirve cuando el correo no llega, cae en spam, o la persona está al lado
    #: del admin — y además no consume la cuota de envíos de Supabase, que es
    #: baja a propósito en el servicio incluido.
    send_email: bool = True


class InvitedUserOut(UserOut):
    """`UserOut` + el enlace, presente solo cuando se pidió sin correo.

    Es una credencial de un solo uso: quien la tenga se convierte en ese
    usuario. Solo la recibe quien ya tiene `identity.manage_users`.
    """

    invite_link: str | None = None


class UpdateUserRoleIn(BaseModel):
    role_id: UUID


class RoleOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    is_seed: bool
    active: bool
    #: Cuántos permisos tiene marcados. Se expone porque un rol en 0 no sirve
    #: para nada —quien lo tenga no puede ni ver la caja ni el inventario— y
    #: sin este dato el listado no lo distinguía de un rol bien configurado.
    permission_count: int = 0


class RoleCreateIn(BaseModel):
    name: str
    description: str | None = None
    clone_from_role_id: UUID | None = None


class RoleRenameIn(BaseModel):
    name: str
    description: str | None = None


class RolePermissionsIn(BaseModel):
    permission_codes: list[str]


class PermissionOut(BaseModel):
    id: UUID
    code: str
    module: str
    action: str
    is_special: bool
    description: str | None


class MeUserOut(BaseModel):
    id: UUID
    full_name: str
    email: str


class MeCompanyOut(BaseModel):
    id: UUID
    name: str
    timezone: str
    logo_url: str | None
    # Lo que necesitan los documentos imprimibles (contrato, acta de cierre,
    # comprobante) va acá y NO solo en `GET /company/settings`: imprimir un
    # contrato lo hace cualquier asesor, y ese endpoint exige el permiso
    # `company.configure`, que un asesor no tiene ni debería tener.
    signature_url: str | None = None
    legal_name: str | None = None
    tax_id: str | None = None
    address: str | None = None
    contact_phone: str | None = None
    documents: "MeDocumentsOut" = Field(default_factory=lambda: MeDocumentsOut())


class MeDocumentsOut(BaseModel):
    header_note: str | None = None
    footer_note: str | None = None
    legal_notice: str | None = None


class MeRoleOut(BaseModel):
    id: UUID
    name: str


class MeSubscriptionOut(BaseModel):
    status: str
    expires_at: date


class MePlanOut(BaseModel):
    code: str
    name: str


class MeOut(BaseModel):
    user: MeUserOut
    company: MeCompanyOut
    role: MeRoleOut
    permissions: list[str]
    subscription: MeSubscriptionOut
    plan: MePlanOut
