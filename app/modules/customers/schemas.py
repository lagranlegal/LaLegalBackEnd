from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

DocType = Literal["cc", "ce", "passport", "nit"]
EmailBasis = Literal["contract", "consent"]
EmailConsentSource = Literal["counter", "contract_form", "import"]

_CONSENT_DOC = (
    "Autorización EXPRESA para recibir avisos por correo (NOTIFICACIONES §9.2-f): "
    "la casilla del mostrador. `true` deja la base en `consent` con fecha y origen "
    "`counter` (si ya la tenía, conserva la fecha original: es la prueba). `false` "
    "la retira: la base vuelve a `contract` si hay un contrato vivo, o a ninguna. "
    "Omitido = no se toca."
)


class CustomerCreateIn(BaseModel):
    full_name: str
    doc_type: DocType
    doc_number: str
    doc_issue_place: str | None = None
    address: str | None = None
    phone: str
    #: `EmailStr` y no `str` pelado (F21-19): hasta el 23/09/2026 la única
    #: validación de formato vivía en el `zod` del front, así que cualquier
    #: otro consumidor —un script de importación, un integrador— escribía
    #: basura sin resistencia. Un correo mal escrito no rebota: el proveedor
    #: se lo traga y el aviso se da por ENTREGADO.
    #: Solo en la ENTRADA: `CustomerOut` sigue con `str | None` a propósito,
    #: porque validar la salida convertiría una fila vieja mal escrita en un
    #: 500 al LEER la ficha — castigar la lectura por un dato que ya está
    #: guardado es el peor resultado posible. La regla es la misma que ya rige
    #: para las letras de proveedor: se valida al escribir, no hacia atrás.
    email: EmailStr | None = None
    email_consent: bool | None = Field(default=None, description=_CONSENT_DOC)
    #: Fotos del documento, en orden: [frente, reverso]. Un documento tiene
    #: dos caras y `doc_photo_url` solo aceptaba una (00050).
    doc_photos: list[str] | None = None
    #: DEPRECADO (00050): usar `doc_photos`. Un bundle viejo del front lo
    #: sigue mandando; se interpreta como la única foto que había.
    doc_photo_url: str | None = None
    notes: str | None = None


class CustomerUpdateIn(BaseModel):
    full_name: str | None = None
    doc_issue_place: str | None = None
    address: str | None = None
    phone: str | None = None
    #: Ver `CustomerCreateIn.email` (F21-19). **Texto acá, y se valida en el
    #: servicio**, por un caso que el esquema no puede ver: un correo guardado
    #: ANTES de la validación que no la pasa. El formulario reenvía el correo
    #: tal como está, y si el esquema lo rechazara, la ficha quedaría
    #: congelada — no se podría corregir ni el teléfono sin adivinar qué campo
    #: arreglar. El servicio acepta el valor IDÉNTICO al guardado y valida
    #: cualquier otro con el mismo `EmailStr`, devolviendo el mismo
    #: `VALIDATION_ERROR` con `email` en `loc`. Mismo contrato, un caso menos.
    email: str | None = Field(default=None, json_schema_extra={"format": "email"})
    email_consent: bool | None = Field(default=None, description=_CONSENT_DOC)
    email_opt_out: bool | None = Field(
        default=None,
        description=(
            "Baja de los avisos por correo registrada en el mostrador (la persona la "
            "pidió en persona). `true` la registra con fecha si no estaba; `false` la "
            "levanta. La baja GANA sobre cualquier base (§9.2-c) pero no la borra. "
            "Omitido = no se toca."
        ),
    )
    #: Fotos del documento, en orden: [frente, reverso]. Un documento tiene
    #: dos caras y `doc_photo_url` solo aceptaba una (00050).
    doc_photos: list[str] | None = None
    #: DEPRECADO (00050): usar `doc_photos`. Un bundle viejo del front lo
    #: sigue mandando; se interpreta como la única foto que había.
    doc_photo_url: str | None = None
    notes: str | None = None


class CustomerOut(BaseModel):
    id: UUID
    full_name: str
    doc_type: str
    doc_number: str
    doc_issue_place: str | None
    address: str | None
    phone: str
    email: str | None
    doc_photos: list[str] = Field(default_factory=list)
    #: DEPRECADO (00050): sale sincronizado con `doc_photos[0]` para que un
    #: bundle viejo del front siga mostrando la foto del frente.
    doc_photo_url: str | None
    status: str
    alert_reason: str | None
    notes: str | None
    created_at: datetime
    #: Base legal del correo (NOTIFICACIONES §9.2). `null` = ninguna: aunque
    #: tenga correo, no se le manda nada.
    email_basis: EmailBasis | None = None
    email_basis_at: datetime | None = None
    #: Solo con `email_basis = consent`: cuándo y dónde autorizó.
    email_consent_at: datetime | None = None
    email_consent_source: EmailConsentSource | None = None
    #: Pidió la baja. Gana sobre cualquier base.
    email_opt_out_at: datetime | None = None
    #: El correo rebotó duro; se limpia al cambiar la dirección.
    email_invalid_at: datetime | None = None
