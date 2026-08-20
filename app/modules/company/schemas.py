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
