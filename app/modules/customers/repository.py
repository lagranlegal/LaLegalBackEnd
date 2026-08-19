from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, full_name, doc_type, doc_number, doc_issue_place, address, phone, email, "
    "doc_photo_url, status, alert_reason, notes, created_at"
)


async def find_by_doc(
    db: AsyncSession, *, company_id: UUID, doc_type: str, doc_number: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select id from public.customer
            where company_id = :company_id and doc_type = :doc_type and doc_number = :doc_number
            """
        ),
        {"company_id": str(company_id), "doc_type": doc_type, "doc_number": doc_number},
    )
    return result.first()


async def insert_customer(
    db: AsyncSession,
    *,
    customer_id: UUID,
    company_id: UUID,
    full_name: str,
    doc_type: str,
    doc_number: str,
    doc_issue_place: str | None,
    address: str | None,
    phone: str,
    email: str | None,
    doc_photo_url: str | None,
    notes: str | None,
    created_by: UUID,
) -> None:
    await db.execute(
        text(
            """
            insert into public.customer
                (id, company_id, full_name, doc_type, doc_number, doc_issue_place, address,
                 phone, email, doc_photo_url, notes, created_by)
            values
                (:id, :company_id, :full_name, :doc_type, :doc_number, :doc_issue_place, :address,
                 :phone, :email, :doc_photo_url, :notes, :created_by)
            """
        ),
        {
            "id": str(customer_id),
            "company_id": str(company_id),
            "full_name": full_name,
            "doc_type": doc_type,
            "doc_number": doc_number,
            "doc_issue_place": doc_issue_place,
            "address": address,
            "phone": phone,
            "email": email,
            "doc_photo_url": doc_photo_url,
            "notes": notes,
            "created_by": str(created_by),
        },
    )


async def get_customer(db: AsyncSession, *, company_id: UUID, customer_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(f"select {_COLUMNS} from public.customer where company_id = :company_id and id = :id"),
        {"company_id": str(company_id), "id": str(customer_id)},
    )
    return result.first()


async def list_customers(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int, q: str | None
) -> list[Row[Any]]:
    query = f"select {_COLUMNS} from public.customer where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if q:
        # Nombre: full-text (fragmentos, tildes, orden de palabras). Documento:
        # coincidencia exacta o por prefijo — en el mostrador se tipea el
        # número completo o casi completo, nunca un fragmento suelto como en
        # un nombre, así que no necesita full-text ahí.
        query += (
            " and (to_tsvector('spanish', full_name) @@ plainto_tsquery('spanish', :q)"
            " or doc_number like :doc_prefix)"
        )
        params["q"] = q
        params["doc_prefix"] = f"{q}%"
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def update_customer(
    db: AsyncSession, *, company_id: UUID, customer_id: UUID, fields: dict[str, Any]
) -> None:
    """`fields` debe venir de `CustomerUpdateIn.model_dump(exclude_unset=True)` en
    service.py — las claves son siempre nombres de columna fijos y conocidos,
    nunca texto de un usuario, así que interpolarlas en el SQL es seguro.
    """
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = {**fields, "company_id": str(company_id), "id": str(customer_id)}
    await db.execute(
        text(
            f"update public.customer set {assignments} where company_id = :company_id and id = :id"
        ),
        params,
    )
