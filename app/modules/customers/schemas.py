from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

DocType = Literal["cc", "ce", "passport", "nit"]


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
    #: Ver `CustomerCreateIn.email` (F21-19).
    email: EmailStr | None = None
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
