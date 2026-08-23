from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.money import Money
from app.modules.inventory.units import ProductUnit

#: De dónde salió la mercancía. Cada uno se costea y se reporta distinto, así
#: que no son etiquetas cosméticas (00033):
#:   purchase       compra a proveedor. Es el único que puede tocar caja.
#:   initial_stock  lo que ya había en la vitrina al arrancar con el sistema.
#:                  No toca caja —esa plata salió antes y afuera— y se excluye
#:                  del costo de mercancía comprada del período.
#:   adjustment_in  sobrante de un conteo físico. Cierra la asimetría de que
#:                  el inventario solo pudiera bajar (existía el egreso por
#:                  ajuste, no la entrada).
#:   other          cajón de sastre. Se conserva, pero exige motivo.
#: `auction` existe en la BD y lo emite el remate; no se acepta por la API.
EntryOriginType = Literal["purchase", "initial_stock", "adjustment_in", "other"]
#: `loss` (00033) no es lo mismo que `damage`: un daño es mercancía que existe
#: y ya no sirve; una pérdida es mercancía que no está.
ExitType = Literal["adjustment", "damage", "supplier_return", "internal_use", "loss"]
PaymentMethod = Literal["cash", "transfer", "other"]


class ItemOut(BaseModel):
    id: UUID
    code: str | None
    name: str
    cat1_id: UUID
    cat2_id: UUID
    cat3_id: UUID
    description: str | None
    origin: str
    supplier_id: UUID | None
    source_contract_id: UUID | None
    #: Solo si el lote lo PRODUJIMOS transformando (00039). Excluyente con
    #: `supplier_id` y `source_contract_id`: son los tres orígenes posibles,
    #: y ninguno de los tres significa mercancía propia sin documento.
    source_transformation_id: UUID | None = None
    cost: Decimal
    sale_price: Decimal | None
    #: Decimal desde 00036: un producto medido en gramos o metros tiene stock
    #: fraccionario. Si su unidad es `unit`, el servicio rechaza fracciones.
    quantity: Decimal
    #: Unidad del PRODUCTO, repetida acá para que quien muestre un lote no
    #: tenga que ir a buscarla — un "12,5" sin unidad no dice nada.
    unit: str
    unit_abbr: str
    status: str
    photos: list[str]
    entry_date: date
    #: Producto al que pertenece este lote (00021). Es lo que permite agrupar
    #: en la lista: dos lotes del mismo producto comparten este id.
    product_id: UUID | None
    #: Consecutivo del lote DENTRO del producto (1, 2, 3…).
    lot_number: int | None
    created_at: datetime


class ItemUpdateIn(BaseModel):
    """Solo FOTOS. Desde 00022 el nombre, la descripción, la categoría y el
    precio pertenecen al producto y se editan con `PATCH /products/{id}`,
    donde el cambio aplica a todos sus lotes — que es el comportamiento
    correcto: dos lotes del mismo producto no pueden llamarse distinto ni
    costar distinto al cliente.

    Las fotos sí son del lote: una pieza de remate tiene las suyas, y un lote
    puede fotografiarse aparte.
    """

    photos: list[str] | None = None


class ItemPublishIn(BaseModel):
    sale_price: Money


class EntryLineIn(BaseModel):
    name: str
    cat1_id: UUID
    cat2_id: UUID
    cat3_id: UUID
    description: str | None = None
    unit_cost: Money
    #: Cuánto entró. Decimal desde 00036 (gramos, metros). El servicio la
    #: valida contra la unidad del producto: `unit` no admite fracciones.
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    #: Unidad del producto — solo se usa cuando la línea CREA el producto; si
    #: ya existe, se conserva la suya (cambiarla reinterpretaría su stock).
    unit: ProductUnit = "unit"
    photos: list[str] = Field(default_factory=list)
    #: Precio de venta del PRODUCTO. Opcional, y si el producto ya tiene uno
    #: no hace falta repetirlo — se conserva el vigente.
    #:
    #: Está acá porque el ingreso es el momento en que la mercancía está en la
    #: mano de quien la registra: es cuando se sabe en cuánto se va a vender.
    #: Antes había que registrar el ingreso, salir, buscar cada lote y
    #: publicarlo uno por uno, así que TODA compra nacía incompleta por diseño
    #: y el borrador —que debería ser la excepción— era el estado normal.
    #:
    #: Con precio y al menos una foto, el lote se publica SOLO (ver
    #: `create_entry`): emite código y queda `available`, listo para vender.
    sale_price: Money | None = None


class EntryCreateIn(BaseModel):
    origin_type: EntryOriginType
    supplier_id: UUID | None = None
    supplier_invoice: str | None = None
    notes: str | None = None
    # Solo para compras. Si viene, la compra se paga EN EL ACTO: exige caja
    # abierta y genera el egreso. Si se omite, la compra queda PENDIENTE de
    # pago —no toca caja, no exige sesión— y se salda después con
    # `POST /inventory/entries/{id}/pay`.
    #
    # Ese es el camino para cargar facturas de días anteriores o de noche con
    # la caja cerrada: el movimiento de caja no puede insertarse en una sesión
    # ya cerrada (es inmutable), así que se registra cuando efectivamente se
    # paga.
    payment_method: PaymentMethod | None = None
    #: Cuándo ENTRÓ la mercancía (no cuándo se digitó). Por defecto hoy; puede
    #: ser pasada, nunca futura.
    entry_date: date | None = None
    #: Cuenta de la que sale el pago, cuando la compra se paga en el acto.
    account_id: UUID | None = None
    lines: list[EntryLineIn] = Field(min_length=1)


class EntryOut(BaseModel):
    id: UUID
    number: int
    origin_type: str
    supplier_id: UUID | None
    supplier_invoice: str | None
    contract_id: UUID | None
    total_cost: Decimal
    notes: str | None
    payment_method: str | None
    entry_date: date
    #: `None` mientras la compra esté pendiente de pago.
    paid_at: datetime | None
    created_at: datetime
    items: list[ItemOut]


class EntryPayIn(BaseModel):
    payment_method: PaymentMethod
    #: Cuenta de la que sale el pago. Si se omite, la predeterminada del medio.
    account_id: UUID | None = None


class ExitLineIn(BaseModel):
    item_id: UUID
    quantity: Decimal = Field(gt=0)


class ExitCreateIn(BaseModel):
    exit_type: ExitType
    reason: str
    lines: list[ExitLineIn] = Field(min_length=1)


class ExitOut(BaseModel):
    id: UUID
    number: int
    exit_type: str
    reason: str
    created_at: datetime


class ProductOut(BaseModel):
    """Un producto con el resumen de sus lotes — la vista agrupada del
    inventario. El PRECIO vive acá (aplica a todos los lotes); el COSTO no
    sube nunca a este nivel: cada lote conserva el suyo (identificación
    específica, NIIF) y por eso acá solo se expone el RANGO, como lectura
    informativa y jamás como valor de costeo.
    """

    id: UUID
    code: str | None
    name: str
    cat1_id: UUID
    cat2_id: UUID
    cat3_id: UUID
    description: str | None
    sale_price: Decimal | None
    is_unique: bool
    active: bool
    #: Lotes vivos (sin contar los dados de baja).
    lot_count: int
    #: Unidades listas para vender — el número que busca el vendedor. En
    #: gramos o metros puede tener decimales.
    available_quantity: Decimal
    #: En qué se mide este producto (00036).
    unit: str
    unit_abbr: str
    #: Rango de costos entre lotes. Una dispersión grande es señal de que el
    #: precio de compra se movió: vale la pena revisar el precio de venta.
    min_cost: Decimal | None
    max_cost: Decimal | None
    #: Cómo se ve este producto (00034). Se toma una vez y la heredan todos
    #: sus lotes — un lote solo tiene fotos propias si hay algo puntual que
    #: documentar. Solo es obligatoria en piezas únicas (remates).
    photos: list[str]
    created_at: datetime


class ProductUpdateIn(BaseModel):
    """Editar el producto afecta a TODOS sus lotes a la vez — ese es el punto.
    El costo no está acá y nunca lo estará: pertenece al lote.
    """

    name: str | None = None
    description: str | None = None
    sale_price: Money | None = None
    active: bool | None = None
    photos: list[str] | None = None
    #: Cambiar la unidad reinterpreta TODO el stock existente (12 unidades no
    #: son 12 gramos), así que solo se acepta mientras el producto no tenga
    #: lotes — lo valida el servicio.
    unit: ProductUnit | None = None


class ProductPurchaseOut(BaseModel):
    """Una compra de ESTE producto: cuándo, a quién y a cuánto.

    Responde las dos preguntas que la lista de productos solo insinúa al
    mostrar el rango de costos entre lotes: **cómo se movió el costo** y **a
    quién conviene comprarle**. El dato estaba completo en la base y no había
    forma de abrirlo.
    """

    entry_id: UUID
    entry_number: int
    entry_date: date
    supplier_id: UUID | None
    supplier_name: str | None
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    lot_code: str | None
    paid_at: datetime | None


class TransformationInputLineIn(BaseModel):
    """Un artículo que se CONSUME. Deja de existir como tal."""

    item_id: UUID
    quantity: Decimal = Field(gt=0)


class TransformationOutputLineIn(BaseModel):
    """Un artículo que se PRODUCE.

    Es una línea de ingreso sin costo: el costo no se digita, se hereda de lo
    consumido. Digitarlo sería justamente el error que esta operación viene a
    evitar — inventar costo o perderlo por el camino.
    """

    name: str
    cat1_id: UUID
    cat2_id: UUID
    cat3_id: UUID
    description: str | None = None
    quantity: Decimal = Field(gt=0)
    unit: ProductUnit = "unit"
    photos: list[str] = Field(default_factory=list)
    sale_price: Money | None = None
    #: Base para repartir el costo cuando salen VARIOS artículos (despiezar un
    #: celular en pantalla, batería y carcasa). Es lo que cada uno vale
    #: relativamente, no un precio: si se omite en todos, el costo se reparte
    #: en partes iguales. Mismo mecanismo que usa el remate para repartir el
    #: saldo del contrato entre las prendas.
    estimated_value: Decimal | None = Field(default=None, ge=0)


class TransformationCreateIn(BaseModel):
    """Fundir, despiezar o armar: entran N artículos y salen M.

    El costo de lo que sale es el de lo que entró más `extra_cost`. No se
    digita en ninguna parte, y ese es el punto: el costo VIAJA.
    """

    inputs: list[TransformationInputLineIn] = Field(min_length=1)
    outputs: list[TransformationOutputLineIn] = Field(min_length=1)
    #: Lo que cobró el tercero (el fundidor, el técnico). Se CAPITALIZA al
    #: costo de lo que sale: es parte de producir el activo, no un gasto del
    #: mes — igual que el flete de una compra.
    extra_cost: Money = Decimal("0")
    #: Obligatorio si `extra_cost > 0`: esa plata sale de algún lado y tiene
    #: que quedar registrada, o el costo sube sin que nadie haya pagado nada.
    payment_method: PaymentMethod | None = None
    account_id: UUID | None = None
    transform_date: date | None = None
    reason: str
    notes: str | None = None


class TransformationOut(BaseModel):
    id: UUID
    number: int
    transform_date: date
    extra_cost: Decimal
    notes: str | None
    created_at: datetime
    #: Costo total que viajó: lo consumido + `extra_cost`. Es lo que ahora
    #: vale lo producido.
    total_cost: Decimal
    #: Lo que se consumió y lo que salió, para poder explicar la operación
    #: sin ir a buscar dos documentos por separado.
    consumed: list[ItemOut]
    produced: list[ItemOut]


#: Qué movió el stock. No son etiquetas cosméticas: cada uno se lee distinto y
#: dos de ellos no existen como fila en ninguna tabla.
#:   entry      ingreso (compra, inventario inicial, sobrante, remate, o lo
#:              que produjo una transformación — `kind_detail` lo dice)
#:   exit       egreso (ajuste, daño, pérdida, devolución a proveedor, consumo
#:              interno, o lo que consumió una transformación)
#:   sale       venta
#:   sale_void  anulación de venta: repone el stock. Se SINTETIZA — anular no
#:              escribe una línea inversa, solo cambia el estado de la venta.
KardexKind = Literal["entry", "exit", "sale", "sale_void"]


class KardexLineOut(BaseModel):
    """Un movimiento del producto, con el saldo DESPUÉS de él."""

    date: date
    kind: KardexKind
    #: El subtipo dentro de `kind`: `origin_type` del ingreso, `exit_type` del
    #: egreso, `status` de la venta.
    kind_detail: str
    #: Documento que lo causó, para poder ir a verlo.
    reference_id: UUID
    reference_number: int
    #: Notas del ingreso, motivo del egreso o de la anulación.
    detail: str | None
    #: LOTE que se movió. El kardex es del producto, pero el movimiento siempre
    #: es de un lote concreto — y su costo es el del lote, nunca un promedio.
    item_id: UUID
    item_code: str | None
    lot_number: int | None
    quantity_in: Decimal
    quantity_out: Decimal
    #: Costo unitario del lote movido.
    unit_cost: Decimal
    #: Unidades en existencia después de este movimiento.
    running_quantity: Decimal
    #: Cuánto cuesta lo que queda después de este movimiento. NO es
    #: `running_quantity × unit_cost`: cada lote conserva su costo, así que es
    #: la suma de lo que costó cada unidad que sigue en inventario.
    running_value: Decimal


class KardexOut(BaseModel):
    """Kardex: el libro auxiliar de inventario de un producto.

    La historia completa en una sola línea de tiempo — cada ingreso, egreso,
    venta y anulación— con saldo de unidades y de costo corriendo.

    Existía el dato y no la pregunta: los movimientos viven en TRES tablas de
    líneas (`inventory_entry_line`, `inventory_exit_line`, `sale_line`) que se
    consultan **hacia adelante** (dado un documento, qué artículos trajo).
    "¿Qué pasó con este producto?" es la dirección contraria, y no la
    respondía nadie.

    LA VALORACIÓN ES POR LOTE. Cada movimiento se valora al costo del lote que
    se movió, nunca a un promedio: identificación específica (NIIF). Dos lotes
    del mismo producto comprados a precios distintos salen cada uno con el
    suyo, y por eso `running_value` no se puede derivar de `running_quantity`.
    """

    product_id: UUID
    name: str
    unit: str
    unit_abbr: str
    from_date: date
    to_date: date

    #: Saldo ANTES del rango — la suma de todo lo anterior a `from_date`.
    opening_quantity: Decimal
    opening_value: Decimal
    total_in: Decimal
    total_out: Decimal
    closing_quantity: Decimal
    closing_value: Decimal
    lines: list[KardexLineOut]


class TransformationSummaryOut(BaseModel):
    """Una fila del historial de transformaciones.

    Trae el resumen de las dos puntas —qué entró, qué salió— porque la
    pregunta que se le hace a esta lista es "¿de dónde salió este oro?", y
    obligar a abrir cada fila para responderla la volvería inútil.

    No incluye `consumed`/`produced` completos a propósito: son dos consultas
    por fila y en una lista de cincuenta transformaciones eso es un problema
    de rendimiento sin nada a cambio. El detalle está en
    `GET /inventory/transformations/{id}`.
    """

    id: UUID
    number: int
    transform_date: date
    #: El motivo que se escribió al fundir/despiezar. Es el título de la fila.
    reason: str
    notes: str | None
    #: Lo que cobró el tercero, ya capitalizado en el costo de lo producido.
    extra_cost: Decimal
    #: Costo total que viajó: lo consumido + `extra_cost`.
    total_cost: Decimal
    input_count: int
    output_count: int
    #: Nombres de producto separados por coma — para leer la fila de corrido.
    input_names: str | None
    output_names: str | None
    created_by_name: str | None
    created_at: datetime
