import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import ConflictError, NotFoundError
from app.modules.customers import repository
from app.modules.customers.schemas import CustomerCreateIn, CustomerOut, CustomerUpdateIn
from app.modules.identity import repository as identity_repo


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
        after={"full_name": body.full_name, "doc_number": body.doc_number},
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
    # Con `before`: son datos personales (Ley 1581) y el documento identifica
    # a quien firmó los contratos. Un cambio ahí hay que poder explicarlo.
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
        after={k: str(v) if v is not None else None for k, v in fields.items()},
    )
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    assert row is not None
    return _row_to_customer(row)
