from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.money import quantize
from app.common.pagination import CursorPage, make_page
from app.core.errors import (
    AppError,
    ConflictError,
    ImportCapitalExceedsPrincipalError,
    ImportDatesMisalignedError,
    NotFoundError,
    PaymentPartialInterestRejectedError,
    PermissionDeniedError,
)
from app.core.security import CurrentUser, has_permission
from app.modules.cashbox import integration as cashbox_integration
from app.modules.catalogs import repository as catalogs_repo
from app.modules.contracts import repository, rules
from app.modules.contracts.schemas import (
    ContractCreateIn,
    ContractExtendIn,
    ContractImportIn,
    ContractItemOut,
    ContractOut,
    ContractUpdateIn,
    ExtensionQuoteOut,
    PaymentCreateIn,
    PaymentOptionOut,
    PaymentOut,
    PaymentQuoteOut,
    SettlementInfoOut,
)
from app.modules.customers import repository as customers_repo
from app.modules.identity import repository as identity_repo
from app.modules.inventory import integration as inventory_integration
from app.modules.platform import integration as platform_integration

_MAX_LEVEL = 3


def _row_to_items(rows: list[Row[Any]]) -> list[ContractItemOut]:
    items = []
    for r in rows:
        m = r._mapping
        items.append(
            ContractItemOut(
                id=m["id"],
                category_id=m["category_id"],
                description=m["description"],
                weight_grams=m["weight_grams"],
                serial_imei=m["serial_imei"],
                item_appraisal=m["item_appraisal"],
                status=m["status"],
                photos=list(m["photos"] or []),
                inventory_item_id=m["inventory_item_id"],
            )
        )
    return items


def _row_to_contract(row: Row[Any], items: list[ContractItemOut]) -> ContractOut:
    m = row._mapping
    return ContractOut(
        id=m["id"],
        number=m["number"],
        legacy_code=m["legacy_code"],
        customer_id=m["customer_id"],
        principal=m["principal"],
        capital_balance=m["capital_balance"],
        appraisal_value=m["appraisal_value"],
        interest_rate_pct=m["interest_rate_pct"],
        term_months=m["term_months"],
        arrears_window_months=m["arrears_window_months"],
        extension_months=m["extension_months"],
        start_date=m["start_date"],
        due_date=m["due_date"],
        interest_paid_until=m["interest_paid_until"],
        status=m["status"],
        extension_ends_at=m["extension_ends_at"],
        ltv_warning=m["ltv_warning"],
        notes=m["notes"],
        signed_photo_url=m["signed_photo_url"],
        created_at=m["created_at"],
        extension_window_days=m["extension_window_days"],
        extension_interest_policy=m["extension_interest_policy"],
        parent_contract_id=m["parent_contract_id"],
        root_contract_id=m["root_contract_id"],
        items=items,
    )


def _row_to_payment(row: Row[Any]) -> PaymentOut:
    m = row._mapping
    return PaymentOut(
        id=m["id"],
        receipt_number=m["receipt_number"],
        paid_at=m["paid_at"],
        months_covered=m["months_covered"],
        interest_amount=m["interest_amount"],
        capital_amount=m["capital_amount"],
        discount_amount=m["discount_amount"],
        discount_reason=m["discount_reason"],
        payment_method=m["payment_method"],
        total=m["total"],
        new_capital_balance=m["new_capital_balance"],
        new_interest_paid_until=m["new_interest_paid_until"],
        created_at=m["created_at"],
    )


async def _check_ltv(
    db: AsyncSession,
    *,
    role_id: UUID,
    principal: Decimal,
    appraisal_value: Decimal | None,
    max_ltv_pct: Decimal | None,
) -> bool:
    """¿Se pasa del LTV? Devuelve la bandera, o bloquea si no hay permiso.

    Hasta 00051 pasarse solo ADVERTÍA, para todos. Ahora depende de
    `contracts.override_ltv` (docs/RECARGOS.md §8.1): quien lo tiene recibe
    la advertencia y queda auditado como quien autorizó; quien no, queda
    bloqueado con un mensaje que dice a quién pedírselo.

    Se descartó una casilla por empresa ("advierte"/"bloquea"): nadie sabe
    responder eso al dar de alta una empresa, y un permiso la expresa igual
    —dárselo a todos o a nadie— y encima cubre el caso que la casilla no
    puede, que el asesor no pueda y el dueño sí.

    Sin tasación o sin LTV en la categoría no hay nada que comparar: se deja
    pasar sin bandera, igual que siempre.
    """
    if not appraisal_value or appraisal_value <= 0 or max_ltv_pct is None:
        return False
    if principal / appraisal_value * 100 <= max_ltv_pct:
        return False
    if not await has_permission(db, role_id, "contracts.override_ltv"):
        raise PermissionDeniedError(
            "El préstamo supera el LTV máximo de la categoría. Pide a un "
            "responsable con el permiso para autorizarlo que lo registre.",
            details={"permission": "contracts.override_ltv", "max_ltv_pct": str(max_ltv_pct)},
        )
    return True


async def create_contract(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: ContractCreateIn,
    created_by: UUID,
    role_id: UUID,
    idempotency_key: str,
) -> ContractOut:
    existing = await repository.find_contract_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return await get_contract(db, company_id=company_id, contract_id=existing._mapping["id"])

    customer = await customers_repo.get_customer(
        db, company_id=company_id, customer_id=body.customer_id
    )
    if customer is None:
        raise NotFoundError("El cliente no existe en esta empresa.")

    categories = []
    for item in body.items:
        category = await catalogs_repo.get_category(
            db, company_id=company_id, category_id=item.category_id
        )
        if category is None:
            raise NotFoundError(
                "Una de las categorías de los artículos no existe.",
                details={"category_id": str(item.category_id)},
            )
        if category._mapping["level"] != _MAX_LEVEL:
            raise AppError(
                "Los artículos deben clasificarse en una categoría de nivel 3 (la más específica).",
                details={"category_id": str(item.category_id)},
            )
        categories.append(category)

    # Los parámetros se HEREDAN del árbol: si la hoja no los define, se toma
    # el ancestro más cercano que sí (`catalogs.resolve_category_params`, sin
    # migración: es lógica de consulta). Antes se leían solo de la hoja,
    # así que los mismos campos en los niveles 1 y 2 no los usaba nadie y
    # olvidar el plazo en UNA hoja rompía la creación de contratos con esa
    # prenda.
    parametros = []
    for category in categories:
        params = await catalogs_repo.resolve_category_params(
            db, company_id=company_id, category_id=category._mapping["id"]
        )
        if params is None:
            raise AppError(
                "No se pudieron resolver los parámetros de la categoría.",
                details={"category_id": str(category._mapping["id"])},
            )
        parametros.append(params._mapping)

    first = parametros[0]
    term_months = first["default_term_months"]
    arrears_window_months = first["arrears_window_months"]
    max_ltv_pct = first["max_ltv_pct"]
    if term_months is None or arrears_window_months is None:
        raise AppError(
            "Ni la categoría del artículo ni ninguna de sus categorías padre tienen "
            "plazo y ventana de mora configurados. Configúralos en Catálogos — si los "
            "pones en una categoría superior, los heredan todas las de abajo.",
            details={"category_id": str(categories[0]._mapping["id"])},
        )
    for m in parametros[1:]:
        if (
            m["default_term_months"] != term_months
            or m["arrears_window_months"] != arrears_window_months
        ):
            raise AppError(
                "Todos los artículos de un contrato deben compartir el mismo plazo "
                "y ventana de mora (categoría)."
            )

    # El desembolso sale por la cuenta elegida; la sesión la exige el tipo de
    # cuenta (efectivo sí, banco no), no la operación. `direction='out'`
    # descarta las cuentas por cobrar: no se le presta al cliente con plata
    # que todavía no ha llegado.
    resolved = await cashbox_integration.resolve_account_for_movement(
        db,
        company_id=company_id,
        payment_method=body.payment_method,
        account_id=body.account_id,
        direction="out",
    )

    start_date = await platform_integration.get_company_today(db, company_id=company_id)
    due_date = rules.add_months(start_date, term_months)

    ltv_warning = await _check_ltv(
        db,
        role_id=role_id,
        principal=body.principal,
        appraisal_value=body.appraisal_value,
        max_ltv_pct=max_ltv_pct,
    )

    # La ventana de recargo sale de la política de la EMPRESA salvo que este
    # contrato traiga la suya. Se congela acá: cambiar la política mañana no
    # puede alterar lo que este cliente firmó hoy.
    extension_window_days = (
        body.extension_window_days
        if body.extension_window_days is not None
        else await platform_integration.get_extension_window_days(db, company_id=company_id)
    )

    contract_id = uuid4()
    number = await repository.next_number(db, company_id=company_id)
    await repository.insert_contract(
        db,
        contract_id=contract_id,
        company_id=company_id,
        number=number,
        legacy_code=body.legacy_code,
        customer_id=body.customer_id,
        principal=body.principal,
        capital_balance=body.principal,
        appraisal_value=body.appraisal_value,
        interest_rate_pct=body.interest_rate_pct,
        term_months=term_months,
        arrears_window_months=arrears_window_months,
        extension_months=body.extension_months,
        start_date=start_date,
        due_date=due_date,
        extension_window_days=extension_window_days,
        interest_paid_until=start_date,
        ltv_warning=ltv_warning,
        notes=body.notes,
        signed_photo_url=None,
        created_by=created_by,
        idempotency_key=idempotency_key,
    )
    for item in body.items:
        await repository.insert_contract_item(
            db,
            item_id=uuid4(),
            company_id=company_id,
            contract_id=contract_id,
            category_id=item.category_id,
            description=item.description,
            weight_grams=item.weight_grams,
            serial_imei=item.serial_imei,
            item_appraisal=item.item_appraisal,
            photos=item.photos,
        )

    await cashbox_integration.record_movement(
        db,
        session_id=resolved.session_id,
        company_id=company_id,
        module="pawn",
        direction="out",
        concept="loan_disbursed",
        amount=body.principal,
        payment_method=body.payment_method,
        reference_type="contract",
        reference_id=contract_id,
        created_by=created_by,
        account_id=resolved.account_id,
    )
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=created_by,
        module="contracts",
        action="create_contract",
        entity_type="contract",
        entity_id=contract_id,
        after={"number": number, "principal": str(body.principal)},
    )

    return await get_contract(db, company_id=company_id, contract_id=contract_id)


async def import_contract(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: ContractImportIn,
    created_by: UUID,
    idempotency_key: str,
) -> ContractOut:
    """docs/MIGRACION_CONTRATOS.md: registra la foto financiera al corte de
    un contrato del sistema anterior. Sin sesión de caja, sin
    cash_movement — el desembolso ya ocurrió en el pasado. `status` se
    inserta `active` y pasa por el mismo recálculo que `get_contract`
    (llamado al final) antes de responder: nunca se acepta un estado en el
    body, un solo origen de verdad.
    """
    existing = await repository.find_contract_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return await get_contract(db, company_id=company_id, contract_id=existing._mapping["id"])

    legacy_existing = await repository.find_contract_by_legacy_code(
        db, company_id=company_id, legacy_code=body.legacy_code
    )
    if legacy_existing is not None:
        raise ConflictError(
            "Ya existe un contrato con ese legacy_code en esta empresa.",
            code="CONTRACT_LEGACY_CODE_EXISTS",
        )

    today = await platform_integration.get_company_today(db, company_id=company_id)
    if body.start_date > today:
        raise AppError("start_date no puede estar en el futuro.")
    if body.term_months <= 0 or body.arrears_window_months <= 0 or body.extension_months <= 0:
        raise AppError(
            "term_months, arrears_window_months y extension_months deben ser mayores a cero."
        )
    if not body.items:
        raise AppError("El contrato debe incluir al menos un artículo.")
    if body.capital_balance <= 0 or body.capital_balance > body.principal:
        raise ImportCapitalExceedsPrincipalError(
            "capital_balance debe ser mayor a cero y no puede superar el principal."
        )

    aligned_months = rules.months_since_start_exact(body.start_date, body.interest_paid_until)
    if aligned_months is None:
        raise ImportDatesMisalignedError(
            "interest_paid_until debe caer en un número entero de meses completos desde start_date."
        )

    customer = await customers_repo.get_customer(
        db, company_id=company_id, customer_id=body.customer_id
    )
    if customer is None:
        raise NotFoundError("El cliente no existe en esta empresa.")

    categories = []
    for item in body.items:
        category = await catalogs_repo.get_category(
            db, company_id=company_id, category_id=item.category_id
        )
        if category is None:
            raise NotFoundError(
                "Una de las categorías de los artículos no existe.",
                details={"category_id": str(item.category_id)},
            )
        if category._mapping["level"] != _MAX_LEVEL:
            raise AppError(
                "Los artículos deben clasificarse en una categoría de nivel 3 (la más específica).",
                details={"category_id": str(item.category_id)},
            )
        categories.append(category)

    due_date = rules.add_months(body.start_date, body.term_months)

    ltv_warning = False
    if body.appraisal_value and body.appraisal_value > 0:
        # También heredado: un LTV puesto en la categoría padre vale
        # para sus hojas.
        params_ltv = await catalogs_repo.resolve_category_params(
            db, company_id=company_id, category_id=categories[0]._mapping["id"]
        )
        max_ltv_pct = params_ltv._mapping["max_ltv_pct"] if params_ltv is not None else None
        if max_ltv_pct is not None:
            ltv_pct = body.principal / body.appraisal_value * 100
            ltv_warning = ltv_pct > max_ltv_pct

    contract_id = uuid4()
    number = await repository.next_number(db, company_id=company_id)
    await repository.insert_contract(
        db,
        contract_id=contract_id,
        company_id=company_id,
        number=number,
        legacy_code=body.legacy_code,
        customer_id=body.customer_id,
        principal=body.principal,
        capital_balance=body.capital_balance,
        appraisal_value=body.appraisal_value,
        interest_rate_pct=body.interest_rate_pct,
        term_months=body.term_months,
        arrears_window_months=body.arrears_window_months,
        extension_months=body.extension_months,
        start_date=body.start_date,
        due_date=due_date,
        interest_paid_until=body.interest_paid_until,
        ltv_warning=ltv_warning,
        notes=body.notes,
        signed_photo_url=body.signed_photo_url,
        created_by=created_by,
        idempotency_key=idempotency_key,
    )
    for item in body.items:
        await repository.insert_contract_item(
            db,
            item_id=uuid4(),
            company_id=company_id,
            contract_id=contract_id,
            category_id=item.category_id,
            description=item.description,
            weight_grams=item.weight_grams,
            serial_imei=item.serial_imei,
            item_appraisal=item.item_appraisal,
            photos=item.photos,
        )

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=created_by,
        module="contracts",
        action="import_contract",
        entity_type="contract",
        entity_id=contract_id,
        after={
            "legacy_code": body.legacy_code,
            "principal": str(body.principal),
            "capital_balance": str(body.capital_balance),
        },
    )

    return await get_contract(db, company_id=company_id, contract_id=contract_id)


async def get_contract(db: AsyncSession, *, company_id: UUID, contract_id: UUID) -> ContractOut:
    row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
    if row is None:
        raise NotFoundError("El contrato no existe en esta empresa.")

    m = row._mapping
    today = await platform_integration.get_company_today(db, company_id=company_id)
    new_status, new_extension_ends_at = rules.compute_status(
        current_status=m["status"],
        interest_paid_until=m["interest_paid_until"],
        arrears_window_months=m["arrears_window_months"],
        extension_months=m["extension_months"],
        extension_ends_at=m["extension_ends_at"],
        today=today,
    )
    if new_status != m["status"] or new_extension_ends_at != m["extension_ends_at"]:
        await repository.update_contract_status(
            db,
            company_id=company_id,
            contract_id=contract_id,
            status=new_status,
            extension_ends_at=new_extension_ends_at,
        )
        row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
        assert row is not None

    items = await repository.list_contract_items(db, company_id=company_id, contract_id=contract_id)
    return _row_to_contract(row, _row_to_items(items))


async def get_settlement_info(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID
) -> SettlementInfoOut:
    """Para el botón "Imprimir paz y salvo" — solo tiene sentido si el
    contrato ya está saldado. `status='paid'` es un estado terminal que
    `create_payment` fija explícitamente al saldar (no lo toca el recálculo
    de `active→in_arrears→in_extension`), así que basta la fila cruda.
    """
    row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
    if row is None:
        raise NotFoundError("El contrato no existe en esta empresa.")
    if row._mapping["status"] != "paid":
        raise NotFoundError("El contrato todavía no está saldado.")

    payment = await repository.get_settlement_payment(
        db, company_id=company_id, contract_id=contract_id
    )
    assert payment is not None, "contrato 'paid' sin abono de saldo — inconsistencia real"
    return SettlementInfoOut(
        settled_at=payment._mapping["paid_at"], receipt_number=payment._mapping["receipt_number"]
    )


async def list_contracts(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    status_filter: str | None,
    customer_id: UUID | None = None,
    q: str | None = None,
) -> CursorPage[ContractOut]:
    rows = await repository.list_contracts(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        status_filter=status_filter,
        customer_id=customer_id,
        q=q,
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    items_out = []
    for row in page.items:
        item_rows = await repository.list_contract_items(
            db, company_id=company_id, contract_id=row._mapping["id"]
        )
        items_out.append(_row_to_contract(row, _row_to_items(item_rows)))
    return CursorPage(items=items_out, next_cursor=page.next_cursor)


async def update_contract(
    db: AsyncSession,
    *,
    company_id: UUID,
    contract_id: UUID,
    body: ContractUpdateIn,
    acting_user_id: UUID,
) -> ContractOut:
    row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
    if row is None:
        raise NotFoundError("El contrato no existe en esta empresa.")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        anterior = {
            campo: str(row._mapping[campo]) if row._mapping[campo] is not None else None
            for campo in fields
        }
        await repository.update_contract_fields(
            db, company_id=company_id, contract_id=contract_id, fields=fields
        )
        # Con `before` y `after`: son los únicos campos editables de un
        # contrato ya firmado —avalúo, notas y la foto del documento
        # firmado— y el avalúo es la referencia de cuánto valía la prenda.
        # Saber que cambió no sirve de nada si no se sabe de cuánto a cuánto.
        await identity_repo.insert_audit_log(
            db,
            company_id=company_id,
            user_id=acting_user_id,
            module="contracts",
            action="update_contract",
            entity_type="contract",
            entity_id=contract_id,
            before=anterior,
            after={k: str(v) if v is not None else None for k, v in fields.items()},
        )
    return await get_contract(db, company_id=company_id, contract_id=contract_id)


async def get_payment_quote(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID
) -> PaymentQuoteOut:
    row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
    if row is None:
        raise NotFoundError("El contrato no existe en esta empresa.")
    m = row._mapping
    today = await platform_integration.get_company_today(db, company_id=company_id)
    quote = rules.quote_payment_options(
        capital_balance=m["capital_balance"],
        interest_rate_pct=m["interest_rate_pct"],
        interest_paid_until=m["interest_paid_until"],
        today=today,
    )
    return PaymentQuoteOut(
        months_owed=quote.months_owed,
        monthly_interest=quote.monthly_interest,
        options=[
            PaymentOptionOut(
                months=o.months,
                interest_amount=o.interest_amount,
                total=o.total,
                allows_capital=o.allows_capital,
            )
            for o in quote.options
        ],
    )


async def create_payment(
    db: AsyncSession,
    *,
    company_id: UUID,
    contract_id: UUID,
    body: PaymentCreateIn,
    user: CurrentUser,
    idempotency_key: str,
) -> PaymentOut:
    existing = await repository.find_payment_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return _row_to_payment(existing)

    contract_row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
    if contract_row is None:
        raise NotFoundError("El contrato no existe en esta empresa.")
    m = contract_row._mapping
    if m["status"] in ("paid", "auctioned"):
        raise AppError("El contrato ya está cerrado; no admite abonos.", code="CONTRACT_CLOSED")

    today = await platform_integration.get_company_today(db, company_id=company_id)
    quote = rules.quote_payment_options(
        capital_balance=m["capital_balance"],
        interest_rate_pct=m["interest_rate_pct"],
        interest_paid_until=m["interest_paid_until"],
        today=today,
    )

    capital_amount = body.capital_amount or Decimal("0")
    if body.months_covered == 0 and capital_amount <= 0:
        raise AppError("El abono no cubre ningún mes de interés ni capital.")
    if body.months_covered > quote.months_owed:
        raise AppError(
            f"Solo se adeudan {quote.months_owed} mes(es) de interés.",
            details={"months_owed": quote.months_owed},
        )
    if capital_amount > 0 and body.months_covered < quote.months_owed:
        raise PaymentPartialInterestRejectedError(
            "El capital solo se abona cuando los intereses quedan al día."
        )

    interest_amount = quantize(quote.monthly_interest * body.months_covered)

    discount_amount = body.discount_amount or Decimal("0")
    if discount_amount > 0:
        if not body.discount_reason:
            raise AppError("El descuento requiere un motivo.")
        if not await has_permission(db, user.role_id, "payments.apply_discount"):
            raise PermissionDeniedError("Falta el permiso 'payments.apply_discount'.")
        if discount_amount > interest_amount:
            raise AppError("El descuento no puede superar el interés del abono.")

    total = interest_amount + capital_amount - discount_amount
    if total <= 0:
        raise AppError("El total del abono debe ser mayor a cero.")

    new_capital_balance = m["capital_balance"] - capital_amount
    if new_capital_balance < 0:
        raise AppError("El abono a capital no puede superar el saldo.")
    new_interest_paid_until = rules.add_months(m["interest_paid_until"], body.months_covered)

    is_full_payoff = new_capital_balance == 0 and body.months_covered == quote.months_owed
    if is_full_payoff:
        new_status: str = "paid"
        new_extension_ends_at: date | None = None
    else:
        new_status, new_extension_ends_at = rules.compute_status(
            current_status=m["status"],
            interest_paid_until=new_interest_paid_until,
            arrears_window_months=m["arrears_window_months"],
            extension_months=m["extension_months"],
            extension_ends_at=None,
            today=today,
        )

    resolved = await cashbox_integration.resolve_account_for_movement(
        db,
        company_id=company_id,
        payment_method=body.payment_method,
        account_id=body.account_id,
    )

    payment_id = uuid4()
    receipt_number = await repository.next_receipt_number(db, company_id=company_id)
    await repository.insert_payment(
        db,
        payment_id=payment_id,
        company_id=company_id,
        contract_id=contract_id,
        receipt_number=receipt_number,
        months_covered=body.months_covered,
        interest_amount=interest_amount,
        capital_amount=capital_amount,
        discount_amount=discount_amount,
        discount_reason=body.discount_reason,
        discount_by=user.id if discount_amount > 0 else None,
        payment_method=body.payment_method,
        total=total,
        new_capital_balance=new_capital_balance,
        new_interest_paid_until=new_interest_paid_until,
        idempotency_key=idempotency_key,
        registered_by=user.id,
    )
    await repository.apply_payment_to_contract(
        db,
        company_id=company_id,
        contract_id=contract_id,
        new_capital_balance=new_capital_balance,
        new_interest_paid_until=new_interest_paid_until,
        status=new_status,
        extension_ends_at=new_extension_ends_at,
    )
    if is_full_payoff:
        await repository.mark_items_returned(db, company_id=company_id, contract_id=contract_id)

    # El cash_movement refleja el efectivo REAL recibido (neto de descuento);
    # contract_payment guarda el desglose bruto para contabilidad.
    net_interest_collected = interest_amount - discount_amount
    if net_interest_collected > 0:
        await cashbox_integration.record_movement(
            db,
            session_id=resolved.session_id,
            company_id=company_id,
            module="pawn",
            direction="in",
            concept="interest_payment",
            amount=net_interest_collected,
            payment_method=body.payment_method,
            reference_type="contract_payment",
            reference_id=payment_id,
            created_by=user.id,
        )
    if capital_amount > 0:
        await cashbox_integration.record_movement(
            db,
            session_id=resolved.session_id,
            company_id=company_id,
            module="pawn",
            direction="in",
            concept="capital_payment",
            amount=capital_amount,
            payment_method=body.payment_method,
            reference_type="contract_payment",
            reference_id=payment_id,
            created_by=user.id,
        )
    # El abono en sí, no solo su descuento. Es la operación de dinero más
    # frecuente del empeño; sin ella, Auditoría no puede responder "¿qué hizo
    # esta persona hoy?" (ver la nota en `sales.create_sale`).
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=user.id,
        module="contracts",
        action="create_payment",
        entity_type="contract_payment",
        entity_id=payment_id,
        after={
            "contract_id": str(contract_id),
            "total": str(total),
            "payment_method": body.payment_method,
        },
    )
    if discount_amount > 0:
        await identity_repo.insert_audit_log(
            db,
            company_id=company_id,
            user_id=user.id,
            module="contracts",
            action="apply_payment_discount",
            entity_type="contract_payment",
            entity_id=payment_id,
            after={
                "discount_amount": str(discount_amount),
                "discount_reason": body.discount_reason,
            },
        )

    row = await repository.find_payment_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    assert row is not None
    return _row_to_payment(row)


async def list_payments(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[PaymentOut]:
    rows = await repository.list_payments(
        db, company_id=company_id, contract_id=contract_id, cursor=cursor, limit=limit
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_payment(r) for r in page.items], next_cursor=page.next_cursor)


async def list_ready_for_auction(db: AsyncSession, *, company_id: UUID) -> list[ContractOut]:
    today = await platform_integration.get_company_today(db, company_id=company_id)
    rows = await repository.list_ready_for_auction(db, company_id=company_id, today=today)
    result = []
    for row in rows:
        item_rows = await repository.list_contract_items(
            db, company_id=company_id, contract_id=row._mapping["id"]
        )
        result.append(_row_to_contract(row, _row_to_items(item_rows)))
    return result


async def recompute_all_statuses(db: AsyncSession) -> int:
    """Job nocturno (CLAUDE.md): recalcula estados de todos los contratos no
    terminales, de todas las empresas. Corre con sesión de bypass (`get_db`,
    no tenant-scoped). Invocable manualmente hasta que exista un scheduler
    real (pg_cron / Fly machine programada) — ver docs/ARCHITECTURE.md.
    """
    rows = await repository.list_active_contracts_for_recompute(db)
    updated = 0
    for row in rows:
        m = row._mapping
        today = await platform_integration.get_company_today(db, company_id=m["company_id"])
        new_status, new_extension_ends_at = rules.compute_status(
            current_status=m["status"],
            interest_paid_until=m["interest_paid_until"],
            arrears_window_months=m["arrears_window_months"],
            extension_months=m["extension_months"],
            extension_ends_at=m["extension_ends_at"],
            today=today,
        )
        if new_status != m["status"] or new_extension_ends_at != m["extension_ends_at"]:
            await repository.update_contract_status(
                db,
                company_id=m["company_id"],
                contract_id=m["id"],
                status=new_status,
                extension_ends_at=new_extension_ends_at,
            )
            updated += 1
    return updated


async def auction_contract(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID, actor_id: UUID
) -> ContractOut:
    """Rematar (CLAUDE.md): decisión humana, ejecución automática. Crea UN
    `inventory_item` en `draft` por cada prenda (`inventory.integration`,
    costo repartido proporcional a tasación), marca contrato y prendas como
    `auctioned`, guarda el vínculo bidireccional. Todo en una transacción.
    """
    contract = await get_contract(db, company_id=company_id, contract_id=contract_id)
    today = await platform_integration.get_company_today(db, company_id=company_id)
    if contract.status != "in_extension" or (
        contract.extension_ends_at is None or contract.extension_ends_at >= today
    ):
        raise ConflictError(
            "El contrato no está listo para rematar (debe estar en prórroga vencida).",
            code="CONTRACT_NOT_READY_FOR_AUCTION",
        )

    row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
    assert row is not None
    m = row._mapping
    quote = rules.quote_payment_options(
        capital_balance=m["capital_balance"],
        interest_rate_pct=m["interest_rate_pct"],
        interest_paid_until=m["interest_paid_until"],
        today=today,
    )
    pending_interest = quantize(quote.monthly_interest * quote.months_owed)
    total_cost = m["capital_balance"] + pending_interest

    item_rows = await repository.list_contract_items(
        db, company_id=company_id, contract_id=contract_id
    )
    auction_items = [
        inventory_integration.AuctionItemInput(
            contract_item_id=r._mapping["id"],
            category_id=r._mapping["category_id"],
            description=r._mapping["description"],
            appraisal=r._mapping["item_appraisal"],
            # Las fotos de la prenda viajan al inventario. Publicar un artículo
            # exige al menos una foto, y hasta ahora el remate creaba el
            # borrador vacío: había que volver a fotografiar una pieza que ya
            # estaba fotografiada desde que se firmó el contrato.
            photos=list(r._mapping["photos"] or []),
        )
        for r in item_rows
    ]

    links = await inventory_integration.create_draft_items_from_auction(
        db,
        company_id=company_id,
        items=auction_items,
        total_cost=total_cost,
        source_contract_id=contract_id,
        created_by=actor_id,
    )
    for contract_item_id, inventory_item_id in links.items():
        await repository.mark_item_auctioned(
            db,
            company_id=company_id,
            contract_item_id=contract_item_id,
            inventory_item_id=inventory_item_id,
        )

    await repository.update_contract_status(
        db,
        company_id=company_id,
        contract_id=contract_id,
        status="auctioned",
        extension_ends_at=None,
    )
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="contracts",
        action="auction_contract",
        entity_type="contract",
        entity_id=contract_id,
        after={"total_cost": str(total_cost), "items_created": len(links)},
    )

    return await get_contract(db, company_id=company_id, contract_id=contract_id)


# ------------------------------------------------- ampliar el préstamo ------
async def _max_ltv_for_contract(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID
) -> Decimal | None:
    """LTV vigente de la categoría de la PRIMERA prenda, heredado del árbol.

    Se lee de la configuración de HOY y no de un snapshot a propósito: el
    cupo es una decisión de riesgo del presente ("¿cuánto le prestaría hoy
    sobre esto?"), no una condición pactada como la tasa. Si el negocio baja
    el LTV, el cupo se achica para todos, y eso es lo correcto.
    """
    items = await repository.list_contract_items(db, company_id=company_id, contract_id=contract_id)
    if not items:
        return None
    params = await catalogs_repo.resolve_category_params(
        db, company_id=company_id, category_id=items[0]._mapping["category_id"]
    )
    return params._mapping["max_ltv_pct"] if params is not None else None


async def quote_extension(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID
) -> ExtensionQuoteOut:
    """Cuánto puede retirar el cliente y hasta cuándo (docs/RECARGOS.md §4).

    Devuelve una respuesta útil SIEMPRE, incluso cuando no se puede ampliar:
    `blocked_reason` dice por qué. Una pantalla que solo sabe "no se puede"
    obliga al usuario a adivinar, y el motivo casi siempre tiene arreglo
    (registrar el avalúo, ponerse al día con los intereses).
    """
    row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
    if row is None:
        raise NotFoundError("El contrato no existe en esta empresa.")
    m = row._mapping
    today = await platform_integration.get_company_today(db, company_id=company_id)

    root_start = await repository.get_root_start_date(
        db, company_id=company_id, contract_id=contract_id
    )
    max_ltv_pct = await _max_ltv_for_contract(
        db, company_id=company_id, contract_id=contract_id
    )
    quote = rules.quote_extension(
        capital_balance=m["capital_balance"],
        appraisal_value=m["appraisal_value"],
        max_ltv_pct=max_ltv_pct,
        root_start_date=root_start,
        extension_window_days=m["extension_window_days"],
    )
    ventana_abierta = rules.extension_window_is_open(
        window_ends_on=quote.window_ends_on, today=today
    )

    # El orden importa: se reporta el motivo que el usuario tiene que
    # resolver PRIMERO. Decirle "no hay cupo" a quien además está en mora lo
    # manda a resolver lo que no lo desbloquea.
    razon: str | None = None
    if m["status"] in ("paid", "auctioned", "superseded"):
        razon = "CONTRACT_CLOSED"
    elif not ventana_abierta:
        razon = "EXTENSION_WINDOW_CLOSED"
    elif rules.months_between(m["interest_paid_until"], today) > 0:
        razon = "CONTRACT_INTEREST_OVERDUE"
    elif quote.ceiling is None:
        razon = "CONTRACT_WITHOUT_APPRAISAL"
    elif quote.available <= 0:
        razon = "EXTENSION_NO_HEADROOM"

    return ExtensionQuoteOut(
        ceiling=quote.ceiling,
        available=quote.available,
        window_ends_on=quote.window_ends_on,
        is_open=razon is None,
        blocked_reason=razon,
    )


async def extend_loan(
    db: AsyncSession,
    *,
    company_id: UUID,
    contract_id: UUID,
    body: ContractExtendIn,
    user: CurrentUser,
    idempotency_key: str,
) -> ContractOut:
    """Amplía el préstamo: el contrato viejo se SUCEDE, no se modifica.

    Por qué no puede ser un `UPDATE` del capital (docs/RECARGOS.md §1): el
    interés se cobra en meses completos anclados a `interest_paid_until` y
    toda la máquina de estados cuelga de esa ancla. Y el papel firmado dice
    un capital — si cambia, ese papel ya no describe la deuda.

    Todo en UNA transacción (CLAUDE.md regla 4).
    """
    existing = await repository.find_contract_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return await get_contract(db, company_id=company_id, contract_id=existing._mapping["id"])

    if body.amount <= 0:
        raise AppError("El monto a entregar debe ser mayor a cero.")

    row = await repository.get_contract(db, company_id=company_id, contract_id=contract_id)
    if row is None:
        raise NotFoundError("El contrato no existe en esta empresa.")
    viejo = row._mapping

    quote = await quote_extension(db, company_id=company_id, contract_id=contract_id)
    if quote.blocked_reason == "CONTRACT_CLOSED":
        raise AppError(
            "El contrato ya está cerrado; no admite ampliaciones.", code="CONTRACT_CLOSED"
        )
    if quote.blocked_reason == "EXTENSION_WINDOW_CLOSED":
        raise ConflictError(
            "Pasó la ventana para ampliar este préstamo."
            + (f" Vencía el {quote.window_ends_on}." if quote.window_ends_on else ""),
            code="EXTENSION_WINDOW_CLOSED",
            details={"window_ends_on": str(quote.window_ends_on)},
        )
    if quote.blocked_reason == "CONTRACT_INTEREST_OVERDUE":
        # El interés adeudado NUNCA se suma al capital nuevo: capitalizar
        # interés es anatocismo, y además volvería el saldo imposible de
        # auditar contra los recibos.
        raise ConflictError(
            "Primero hay que ponerse al día con los intereses. Registra el "
            "abono y vuelve a intentarlo.",
            code="CONTRACT_INTEREST_OVERDUE",
        )
    if quote.blocked_reason == "CONTRACT_WITHOUT_APPRAISAL":
        raise ConflictError(
            "Sin avalúo no se puede calcular cuánto puede retirar el cliente. "
            "Regístralo en Editar y vuelve a intentarlo.",
            code="CONTRACT_WITHOUT_APPRAISAL",
        )

    # Pasarse del cupo es la misma decisión que prestar por encima del LTV al
    # crear: lo gobierna `contracts.override_ltv`, no una casilla (§8.1).
    ltv_warning = bool(viejo["ltv_warning"])
    if body.amount > quote.available:
        if not await has_permission(db, user.role_id, "contracts.override_ltv"):
            raise PermissionDeniedError(
                f"El cliente puede retirar hasta {quote.available} sobre esta garantía. "
                "Pide a un responsable con el permiso para autorizarlo que lo registre.",
                details={
                    "permission": "contracts.override_ltv",
                    "available": str(quote.available),
                },
            )
        ltv_warning = True

    today = await platform_integration.get_company_today(db, company_id=company_id)
    nuevo_capital = quantize(viejo["capital_balance"] + body.amount)

    # --- El sucesor -------------------------------------------------------
    nuevo_id = uuid4()
    number = await repository.next_number(db, company_id=company_id)
    await repository.insert_contract(
        db,
        contract_id=nuevo_id,
        company_id=company_id,
        number=number,
        legacy_code=None,
        customer_id=viejo["customer_id"],
        principal=nuevo_capital,
        capital_balance=nuevo_capital,
        appraisal_value=viejo["appraisal_value"],
        # Tasa, plazo, ventana y prórroga se COPIAN del viejo, no se releen de
        # la categoría: ampliar no renegocia lo pactado.
        interest_rate_pct=viejo["interest_rate_pct"],
        term_months=viejo["term_months"],
        arrears_window_months=viejo["arrears_window_months"],
        extension_months=viejo["extension_months"],
        start_date=today,
        due_date=rules.add_months(today, viejo["term_months"]),
        # El reloj se reinicia: los días corridos sobre el capital viejo se
        # perdonan (política `forgive`, §8.2). Acotado por la ventana.
        interest_paid_until=today,
        ltv_warning=ltv_warning,
        notes=viejo["notes"],
        # Nace SIN foto firmada: hay que imprimirlo y firmarlo. Esa es su
        # razón de ser.
        signed_photo_url=None,
        created_by=user.id,
        idempotency_key=idempotency_key,
        extension_window_days=viejo["extension_window_days"],
        extension_interest_policy=viejo["extension_interest_policy"],
        parent_contract_id=contract_id,
        # La ventana se mide desde la RAÍZ de la cadena, así que el sucesor
        # hereda la raíz del viejo — o al viejo mismo si era el primero.
        root_contract_id=viejo["root_contract_id"] or contract_id,
    )

    # Las mismas prendas, en filas nuevas: `contract_item` cuelga de
    # `contract_id`, y las viejas quedan como evidencia de qué respaldaba el
    # contrato anterior.
    items_viejos = await repository.list_contract_items(
        db, company_id=company_id, contract_id=contract_id
    )
    for item in items_viejos:
        im = item._mapping
        await repository.insert_contract_item(
            db,
            item_id=uuid4(),
            company_id=company_id,
            contract_id=nuevo_id,
            category_id=im["category_id"],
            description=im["description"],
            weight_grams=im["weight_grams"],
            serial_imei=im["serial_imei"],
            item_appraisal=im["item_appraisal"],
            photos=list(im["photos"] or []),
        )

    # --- El viejo se cierra ----------------------------------------------
    await repository.update_contract_status(
        db,
        company_id=company_id,
        contract_id=contract_id,
        status="superseded",
        extension_ends_at=None,
    )
    await repository.mark_items_transferred(db, company_id=company_id, contract_id=contract_id)

    # --- La caja: SOLO el delta ------------------------------------------
    # El capital viejo ya salió el día del contrato original. Volver a moverlo
    # lo contaría dos veces en `/reports/pawn-performance`.
    resolved = await cashbox_integration.resolve_account_for_movement(
        db,
        company_id=company_id,
        payment_method=body.payment_method,
        account_id=body.account_id,
        direction="out",
    )
    await cashbox_integration.record_movement(
        db,
        session_id=resolved.session_id,
        company_id=company_id,
        module="pawn",
        direction="out",
        concept="loan_disbursed",
        amount=body.amount,
        payment_method=body.payment_method,
        reference_type="contract",
        reference_id=nuevo_id,
        created_by=user.id,
        account_id=resolved.account_id,
    )

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=user.id,
        module="contracts",
        action="extend_loan",
        entity_type="contract",
        entity_id=nuevo_id,
        before={
            "contract_id": str(contract_id),
            "number": str(viejo["number"]),
            "capital_balance": str(viejo["capital_balance"]),
        },
        after={
            "number": str(number),
            "amount_disbursed": str(body.amount),
            "capital_balance": str(nuevo_capital),
            "ltv_warning": str(ltv_warning),
        },
    )
    return await get_contract(db, company_id=company_id, contract_id=nuevo_id)
