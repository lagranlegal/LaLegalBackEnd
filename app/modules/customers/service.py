import json
from typing import Any
from uuid import UUID, uuid4

from fastapi.exceptions import RequestValidationError
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import ConflictError, NotFoundError
from app.modules.contracts import integration as contracts_integration
from app.modules.customers import repository
from app.modules.customers.repository import NOW
from app.modules.customers.schemas import CustomerCreateIn, CustomerOut, CustomerUpdateIn
from app.modules.identity import repository as identity_repo

_EMAIL = TypeAdapter(EmailStr)

#: La casilla del mostrador (NOTIFICACIONES §9.2-f). Es el único origen que
#: escribe hoy la API: `contract_form` (§1c) todavía no tiene pantalla.
_COUNTER = "counter"


def _consent_fields() -> dict[str, Any]:
    return {
        "email_basis": "consent",
        "email_basis_at": NOW,
        "email_consent_at": NOW,
        "email_consent_source": _COUNTER,
    }


def _validate_email(value: str) -> str:
    """El mismo `EmailStr` del alta, con el mismo contrato de error:
    `422 VALIDATION_ERROR` y `email` en `details.errors[].loc`."""
    try:
        return str(_EMAIL.validate_python(value))
    except ValidationError as exc:
        raise RequestValidationError(
            [{**e, "loc": ("body", "email")} for e in exc.errors(include_url=False)]
        ) from exc


def _resolver_fotos(
    doc_photos: list[str] | None, doc_photo_url: str | None
) -> tuple[list[str], str | None]:
    """Concilia el campo nuevo con el deprecado (00050).

    Un documento tiene dos caras, así que `doc_photos` es la verdad. Pero
    `doc_photo_url` se sigue aceptando y devolviendo porque el despliegue no
    es atómico: entre que sale el backend y sale el front hay una ventana en
    la que el bundle viejo manda y lee el campo único, y en esa ventana
    registrar un cliente no puede perder su foto.

    `doc_photos` gana siempre que venga. Si solo viene el deprecado, se
    interpreta como lo que era: la única foto, que es el frente.
    """
    if doc_photos is not None:
        return doc_photos, (doc_photos[0] if doc_photos else None)
    if doc_photo_url is not None:
        return [doc_photo_url], doc_photo_url
    return [], None


def _row_to_customer(row: Row[Any]) -> CustomerOut:
    m = row._mapping
    return CustomerOut(
        id=m["id"],
        full_name=m["full_name"],
        doc_type=m["doc_type"],
        doc_number=m["doc_number"],
        doc_issue_place=m["doc_issue_place"],
        address=m["address"],
        phone=m["phone"],
        email=m["email"],
        doc_photos=list(m["doc_photos"] or []),
        doc_photo_url=m["doc_photo_url"],
        status=m["status"],
        alert_reason=m["alert_reason"],
        notes=m["notes"],
        created_at=m["created_at"],
        email_basis=m["email_basis"],
        email_basis_at=m["email_basis_at"],
        email_consent_at=m["email_consent_at"],
        email_consent_source=m["email_consent_source"],
        email_opt_out_at=m["email_opt_out_at"],
        email_invalid_at=m["email_invalid_at"],
    )


async def create_customer(
    db: AsyncSession, *, company_id: UUID, body: CustomerCreateIn, created_by: UUID
) -> CustomerOut:
    existing = await repository.find_by_doc(
        db, company_id=company_id, doc_type=body.doc_type, doc_number=body.doc_number
    )
    if existing is not None:
        raise ConflictError(
            "Ya existe un cliente con ese tipo y número de documento en esta empresa.",
            details={"doc_type": body.doc_type, "doc_number": body.doc_number},
        )

    fotos, foto_principal = _resolver_fotos(body.doc_photos, body.doc_photo_url)

    customer_id = uuid4()
    await repository.insert_customer(
        db,
        customer_id=customer_id,
        company_id=company_id,
        full_name=body.full_name,
        doc_type=body.doc_type,
        doc_number=body.doc_number,
        doc_issue_place=body.doc_issue_place,
        address=body.address,
        phone=body.phone,
        email=body.email,
        doc_photo_url=foto_principal,
        doc_photos=json.dumps(fotos),
        notes=body.notes,
        created_by=created_by,
    )
    # §9.2-f: la casilla marcada al registrar la ficha. Sin casilla no hay
    # base: dar el correo no es autorizar nada, y un cliente recién creado no
    # tiene contrato que la sostenga.
    if body.email_consent:
        await repository.update_customer(
            db, company_id=company_id, customer_id=customer_id, fields=_consent_fields()
        )
    # `customers` no auditaba NADA. Dar de alta a un cliente es la puerta de
    # entrada de todo lo demás —un contrato o una venta cuelgan de él— y con
    # datos personales de por medio (Habeas Data, Ley 1581): quién lo registró
    # y cuándo es justo lo que hay que poder responder.
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=created_by,
        module="customers",
        action="create_customer",
        entity_type="customer",
        entity_id=customer_id,
        after={
            "full_name": body.full_name,
            "doc_number": body.doc_number,
            "email_basis": "consent" if body.email_consent else None,
        },
    )
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    assert row is not None
    return _row_to_customer(row)


async def get_customer(db: AsyncSession, *, company_id: UUID, customer_id: UUID) -> CustomerOut:
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    if row is None:
        raise NotFoundError("El cliente no existe en esta empresa.")
    return _row_to_customer(row)


async def list_customers(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int, q: str | None
) -> CursorPage[CustomerOut]:
    rows = await repository.list_customers(
        db, company_id=company_id, cursor=cursor, limit=limit, q=q
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_customer(r) for r in page.items], next_cursor=page.next_cursor)


async def update_customer(
    db: AsyncSession,
    *,
    company_id: UUID,
    customer_id: UUID,
    body: CustomerUpdateIn,
    acting_user_id: UUID,
) -> CustomerOut:
    current = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    if current is None:
        raise NotFoundError("El cliente no existe en esta empresa.")

    fields = body.model_dump(exclude_unset=True)
    consent = fields.pop("email_consent", None)
    opt_out = fields.pop("email_opt_out", None)
    fields.update(await _email_basis_changes(db, company_id, current, fields, consent, opt_out))
    # Las dos claves viajan juntas o no viajan: escribir una sin la otra las
    # dejaría contradiciéndose, que es el modo exacto en que una migración de
    # expandir/contraer se rompe.
    if "doc_photos" in fields or "doc_photo_url" in fields:
        fotos, foto_principal = _resolver_fotos(
            fields.get("doc_photos"), fields.get("doc_photo_url")
        )
        fields["doc_photos"] = json.dumps(fotos)
        fields["doc_photo_url"] = foto_principal

    await repository.update_customer(
        db, company_id=company_id, customer_id=customer_id, fields=fields
    )
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    assert row is not None
    if not fields:
        return _row_to_customer(row)
    # Lo que la base puso con `now()` se audita con el valor que quedó.
    written = {k: (row._mapping[k] if v is NOW else v) for k, v in fields.items()}
    # Con `before`: son datos personales (Ley 1581) y el documento identifica
    # a quien firmó los contratos. Un cambio ahí hay que poder explicarlo. La
    # base legal y la baja van en el mismo registro: son la respuesta a
    # "¿quién dijo que se le podía escribir, y cuándo?".
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="customers",
        action="update_customer",
        entity_type="customer",
        entity_id=customer_id,
        before={
            campo: str(current._mapping[campo]) if current._mapping[campo] is not None else None
            for campo in fields
            if campo in current._mapping
        },
        after={k: str(v) if v is not None else None for k, v in written.items()},
    )
    return _row_to_customer(row)


async def _email_basis_changes(
    db: AsyncSession,
    company_id: UUID,
    current: Row[Any],
    fields: dict[str, Any],
    consent: bool | None,
    opt_out: bool | None,
) -> dict[str, Any]:
    """Qué columnas de la base legal cambian con este PATCH (§9.2).

    Reglas, en orden:
    1. **Correo:** se valida solo si CAMBIA (ver `CustomerUpdateIn.email`). Una
       dirección nueva borra la marca de rebote: esa marca hablaba de la vieja.
    2. **Casilla:** `true` → `consent` (conservando la fecha si ya la tenía);
       `false` → se retira, y la base cae a `contract` si hay contrato vivo.
    3. **Correo nuevo sin base, con contrato vivo** → `contract`. El correo casi
       nunca está el día del contrato (§1c); si la base solo naciera ahí, el
       que lo da una semana después quedaría sin base para siempre.
    4. **Baja:** se registra o se levanta; nunca borra la base, la tapa.
    """
    m = current._mapping
    changes: dict[str, Any] = {}

    email_changed = False
    if "email" in fields:
        new_email = fields["email"]
        if new_email is not None and new_email != m["email"]:
            new_email = _validate_email(new_email)
            changes["email"] = new_email
        email_changed = new_email != m["email"]
        if email_changed and m["email_invalid_at"] is not None:
            changes["email_invalid_at"] = None
    email_after = changes.get("email", fields.get("email", m["email"]))
    has_email = bool((email_after or "").strip())

    basis = m["email_basis"]
    if consent is True and basis != "consent":
        changes.update(_consent_fields())
        basis = "consent"
    elif consent is False and basis == "consent":
        live = has_email and await contracts_integration.has_live_contract(
            db, company_id=company_id, customer_id=m["id"]
        )
        basis = "contract" if live else None
        changes.update(
            email_basis=basis,
            email_basis_at=NOW if basis else None,
            email_consent_at=None,
            email_consent_source=None,
        )

    if (
        basis is None
        and email_changed
        and has_email
        and consent is not False
        and await contracts_integration.has_live_contract(
            db, company_id=company_id, customer_id=m["id"]
        )
    ):
        changes.update(email_basis="contract", email_basis_at=NOW)

    if opt_out is True and m["email_opt_out_at"] is None:
        changes["email_opt_out_at"] = NOW
    elif opt_out is False and m["email_opt_out_at"] is not None:
        changes["email_opt_out_at"] = None
    return changes
