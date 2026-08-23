import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field

AppliesTo = Literal["pawn", "store", "both"]
DocType = Literal["cc", "ce", "passport", "nit"]

_SOLO_LETRAS = re.compile(r"^[A-Z]+$")

#: Letras que el emisor de códigos usa para decir de dónde salió una pieza
#: cuando NO hay proveedor, y que por eso un proveedor no puede tomar:
#:
#:   R  remate           (00006)
#:   P  propio           inventario inicial o sobrante de conteo (00033)
#:   T  transformado     fundido, despiezado o armado acá (00039)
#:
#: Sin esta reserva, un proveedor llamado "Rodríguez" con letra `R` producía
#: artículos con código indistinguible de los rematados — y el remate es el
#: caso donde el origen tiene consecuencias legales, porque esa pieza fue la
#: prenda de un cliente.
#:
#: Solo se valida al ESCRIBIR. Los proveedores que ya tuvieran una de estas
#: letras siguen funcionando: prohibirlas hacia atrás rompería códigos ya
#: impresos y pegados a la mercancía, que son inmutables por diseño.
RESERVED_SUPPLIER_LETTERS = frozenset({"R", "P", "T"})


def _normalizar_letra(valor: str) -> str:
    """Mayúscula y solo A-Z.

    La mayúscula no es cosmética: el índice de unicidad distingue mayúsculas,
    así que sin normalizar convivían un proveedor `r` y otro `R` como dos
    proveedores distintos, generando códigos que solo se diferencian por algo
    invisible en una etiqueta impresa.

    Y solo A-Z ASCII —nada de `Ñ`, dígitos ni signos— porque el código termina
    en una etiqueta que alguien escribe a mano en un buscador.
    """
    limpio = valor.strip().upper()
    if not _SOLO_LETRAS.match(limpio):
        raise ValueError("La letra de código solo admite letras de la A a la Z.")
    return limpio


def _letra_de_proveedor(valor: str) -> str:
    if valor in RESERVED_SUPPLIER_LETTERS:
        raise ValueError(
            f"La letra «{valor}» está reservada por el sistema para el origen de la "
            "mercancía (R remate, P propio, T transformado). Elige otra."
        )
    return valor


CodeLetter = Annotated[str, Field(min_length=1, max_length=3), AfterValidator(_normalizar_letra)]
SupplierCodeLetter = Annotated[CodeLetter, AfterValidator(_letra_de_proveedor)]


class CategoryCreateIn(BaseModel):
    parent_id: UUID | None = None
    name: str
    code_letter: CodeLetter
    applies_to: AppliesTo = "both"
    default_term_months: int | None = None
    arrears_window_months: int | None = None
    max_ltv_pct: Decimal | None = None


class CategoryUpdateIn(BaseModel):
    name: str | None = None
    code_letter: CodeLetter | None = None
    applies_to: AppliesTo | None = None
    default_term_months: int | None = None
    arrears_window_months: int | None = None
    max_ltv_pct: Decimal | None = None
    active: bool | None = None


class CategoryOut(BaseModel):
    id: UUID
    parent_id: UUID | None
    level: int
    name: str
    code_letter: str
    applies_to: str
    default_term_months: int | None
    arrears_window_months: int | None
    max_ltv_pct: Decimal | None
    active: bool


class SupplierCreateIn(BaseModel):
    name: str
    doc_type: DocType | None = None
    doc_number: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    code_letter: SupplierCodeLetter
    notes: str | None = None


class SupplierUpdateIn(BaseModel):
    name: str | None = None
    doc_type: DocType | None = None
    doc_number: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    code_letter: SupplierCodeLetter | None = None
    notes: str | None = None
    active: bool | None = None


class SupplierOut(BaseModel):
    id: UUID
    name: str
    doc_type: str | None
    doc_number: str | None
    phone: str | None
    email: str | None
    address: str | None
    code_letter: str
    notes: str | None
    active: bool


class SupplierPurchaseOut(BaseModel):
    """Una compra a este proveedor, en su ficha."""

    entry_id: UUID
    number: int
    entry_date: date
    supplier_invoice: str | None
    total_cost: Decimal
    item_count: int
    paid_at: datetime | None


class SupplierSummaryOut(BaseModel):
    """Ficha del proveedor: qué le he comprado y cuánto le debo.

    El CLIENTE ya tenía su ficha con historial cruzado desde el paso 4; el
    proveedor tenía un formulario de creación y nada más. Sin esto no había
    forma de responder "¿cuánto le he comprado?" ni "¿le debo algo?" aunque el
    dato estuviera completo en la base.
    """

    supplier_id: UUID
    name: str
    code_letter: str
    purchase_count: int
    total_purchased: Decimal
    #: Compras registradas y todavía sin pagar.
    pending_count: int
    pending_total: Decimal
    first_purchase_date: date | None
    last_purchase_date: date | None
    #: Productos distintos que se le han comprado.
    product_count: int
