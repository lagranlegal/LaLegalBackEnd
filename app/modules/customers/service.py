from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import ConflictError, NotFoundError
from app.modules.customers import repository
from app.modules.customers.schemas import CustomerCreateIn, CustomerOut, CustomerUpdateIn


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
        doc_photo_url=body.doc_photo_url,
        notes=body.notes,
        created_by=created_by,
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
    db: AsyncSession, *, company_id: UUID, customer_id: UUID, body: CustomerUpdateIn
) -> CustomerOut:
    current = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    if current is None:
        raise NotFoundError("El cliente no existe en esta empresa.")

    fields = body.model_dump(exclude_unset=True)
    await repository.update_customer(
        db, company_id=company_id, customer_id=customer_id, fields=fields
    )
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    assert row is not None
    return _row_to_customer(row)
