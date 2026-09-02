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


class RecoveryLinkOut(BaseModel):
    """Enlace de recuperación de contraseña, para entregar a mano.

    Misma naturaleza que `invite_link`: es una credencial de un solo uso —
    quien la tenga puede cambiar esa contraseña y entrar como esa persona.
    """

    user_id: UUID
    email: str
    recovery_link: str


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
    #: Foto de perfil del usuario (bucket privado, el front resuelve la URL
    #: firmada). La edita el propio usuario desde `PATCH /me`.
    photo_url: str | None = None


class MeUpdateIn(BaseModel):
    """Lo que un usuario puede cambiar DE SÍ MISMO, sin permisos de
    identidad: su nombre y su foto. Nada más.

    Fuera a propósito: `email` es la identidad de Supabase Auth y cambiarlo
    es un flujo aparte (verificación incluida); `role_id`/`status` son
    gestión de identidad y exigen `identity.manage_users` — si se pudieran
    tocar acá, cualquiera se ascendería a admin editando su perfil.

    PATCH parcial (`exclude_unset`): omitir un campo lo conserva, mandar
    `null` explícito en `photo_url` borra la foto.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    photo_url: str | None = None


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
