from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentSettingsOut(BaseModel):
    """Textos configurables de los documentos imprimibles (contrato, acta de
    cierre, comprobante de venta). Viven en `company.settings->documents`, no
    en columnas propias: son texto libre de presentación, no datos de negocio
    que alguien vaya a consultar o agregar.
    """

    header_note: str | None = None
    footer_note: str | None = None
    legal_notice: str | None = None


class DocumentSettingsIn(BaseModel):
    header_note: str | None = Field(default=None, max_length=200)
    footer_note: str | None = Field(default=None, max_length=300)
    legal_notice: str | None = Field(default=None, max_length=1000)


class CompanySettingsOut(BaseModel):
    id: UUID
    name: str
    legal_name: str | None
    tax_id: str | None
    contact_email: str | None
    contact_phone: str | None
    address: str | None
    logo_url: str | None
    signature_url: str | None
    # Solo lectura acá: cambiar la zona horaria cambia en silencio el "hoy" con
    # el que se calculan mora, prórrogas y cierres de caja — no es un ajuste de
    # presentación y no debería editarse desde la misma pantalla que el logo.
    timezone: str
    currency: str
    documents: DocumentSettingsOut
    #: Plazo de devolución de cliente, en días desde la venta. 0 = sin
    #: límite. Es una ADVERTENCIA, no un bloqueo duro (no hay un plazo legal
    #: fijo en Colombia para devoluciones en tienda física que justifique
    #: prohibirlo del todo): pasado el plazo, la devolución se rechaza salvo
    #: que quien la registra tenga `sales.return_override_time_limit`.
    return_window_days: int


class CompanySettingsUpdateIn(BaseModel):
    """PATCH parcial: solo los campos presentes se escriben (`exclude_unset`),
    así que mandar `null` explícito SÍ borra el valor y omitirlo lo conserva.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    legal_name: str | None = None
    tax_id: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    logo_url: str | None = None
    signature_url: str | None = None
    documents: DocumentSettingsIn | None = None
    return_window_days: int | None = Field(default=None, ge=0)


DocumentType = Literal["contract", "settlement"]


class DocumentTemplateOut(BaseModel):
    """`body` es el documento ProseMirror/Tiptap completo (JSON estructurado,
    nunca HTML crudo — esa es la mitigación de XSS: el renderer del frontend
    solo emite las etiquetas que sus nodos conocidos definen)."""

    id: UUID
    document_type: DocumentType
    name: str
    body: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DocumentTemplateCreateIn(BaseModel):
    document_type: DocumentType
    name: str = Field(min_length=1, max_length=100)
    body: dict[str, Any]


class DocumentTemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    body: dict[str, Any] | None = None
