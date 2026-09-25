from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.search import name_clauses

#: Marcador para `update_customer`: "esta columna vale `now()`".
NOW = object()

_COLUMNS = (
    "id, full_name, doc_type, doc_number, doc_issue_place, address, phone, email, "
    "doc_photo_url, doc_photos, status, alert_reason, notes, created_at, "
    "email_basis, email_basis_at, email_consent_at, email_consent_source, "
    "email_opt_out_at, email_invalid_at"
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
    doc_photos: str,
    notes: str | None,
    created_by: UUID,
) -> None:
    await db.execute(
        text(
            """
            insert into public.customer
                (id, company_id, full_name, doc_type, doc_number, doc_issue_place, address,
                 phone, email, doc_photo_url, doc_photos, notes, created_by)
            values
                (:id, :company_id, :full_name, :doc_type, :doc_number, :doc_issue_place, :address,
                 :phone, :email, :doc_photo_url, cast(:doc_photos as jsonb), :notes, :created_by)
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
            "doc_photos": doc_photos,
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
        # Nombre: full-text CON PREFIJO en la última palabra (`common/search.py`).
        # Antes era `plainto_tsquery`, que compara lexemas enteros: "Mateo"
        # encontraba a Mateo y "Mate" no encontraba nada. Documento: prefijo —
        # en el mostrador se teclea el número completo o casi, nunca un
        # fragmento suelto como en un nombre, así que no necesita full-text.
        #
        # Acá NO hay piso de caracteres, y es a propósito: este listado no
        # tiene con qué confundirse. El piso de tres vive en contratos, donde
        # un documento corto compite con un número de contrato, y en la
        # pantalla, que no dispara la consulta antes.
        clauses, name_params = name_clauses("full_name", q, prefix="name")
        clauses.append("doc_number like :doc_prefix")
        query += " and (" + " or ".join(clauses) + ")"
        params.update(name_params)
        params["doc_prefix"] = f"{q.strip()}%"
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
    # `doc_photos` es `jsonb`: sin el cast, asyncpg manda el string y Postgres
    # se niega a asignarlo a la columna. El resto de las columnas son
    # escalares y no lo necesitan.
    # Las columnas de fecha de la base legal aceptan el literal `now()` (ver
    # `service._email_basis_changes`): la hora la pone la base, en la misma
    # transacción, no el reloj del proceso.
    now_cols = {k for k, v in fields.items() if v is NOW}
    assignments = ", ".join(
        f"{key} = now()"
        if key in now_cols
        else f"{key} = cast(:{key} as jsonb)"
        if key == "doc_photos"
        else f"{key} = :{key}"
        for key in fields
    )
    fields = {k: v for k, v in fields.items() if k not in now_cols}
    params = {**fields, "company_id": str(company_id), "id": str(customer_id)}
    await db.execute(
        text(
            f"update public.customer set {assignments} where company_id = :company_id and id = :id"
        ),
        params,
    )


async def set_contract_basis_if_missing(
    db: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> bool:
    """Escribe la base `contract` si el cliente tiene correo y NINGUNA base.
    Nunca pisa `consent` (cubre lo mismo y más, y su fecha es la prueba)."""
    result = await db.execute(
        text(
            """
            update public.customer
               set email_basis = 'contract', email_basis_at = now()
             where company_id = :company_id and id = :id
               and email_basis is null
               and nullif(btrim(email), '') is not null
            returning id
            """
        ),
        {"company_id": str(company_id), "id": str(customer_id)},
    )
    return result.first() is not None


async def mark_opted_out(
    db: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> tuple[bool, datetime | None]:
    """Pone `email_opt_out_at` si no estaba. Devuelve (si cambió, la fecha)."""
    result = await db.execute(
        text(
            """
            update public.customer
               set email_opt_out_at = now()
             where company_id = :company_id and id = :id and email_opt_out_at is null
            returning email_opt_out_at
            """
        ),
        {"company_id": str(company_id), "id": str(customer_id)},
    )
    row = result.first()
    if row is not None:
        return True, row[0]
    current = await get_customer(db, company_id=company_id, customer_id=customer_id)
    return False, current._mapping["email_opt_out_at"] if current else None
