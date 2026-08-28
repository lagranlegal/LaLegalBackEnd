import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, name, legal_name, tax_id, contact_email, contact_phone, address, "
    "logo_url, signature_url, settings"
)

# Columnas que el tenant puede editar de su propia empresa. `status` y las
# fechas quedan fuera a propósito: suspender o activar una empresa es del
# super-admin (módulo `platform`), no de la empresa sobre sí misma.
EDITABLE_COLUMNS = frozenset(
    {
        "name",
        "legal_name",
        "tax_id",
        "contact_email",
        "contact_phone",
        "address",
        "logo_url",
        "signature_url",
    }
)


async def get_company(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(f"select {_COLUMNS} from public.company where id = :id"),
        {"id": str(company_id)},
    )
    return result.first()


async def update_company(
    db: AsyncSession,
    *,
    company_id: UUID,
    fields: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> None:
    """`fields` viene de `CompanySettingsUpdateIn.model_dump(exclude_unset=True)`
    filtrado contra `EDITABLE_COLUMNS` en el servicio — nunca texto libre del
    usuario en la posición de un nombre de columna.

    `settings` se manda YA fusionado por el servicio (jsonb completo), no como
    parche: un `||` a ciegas acá dejaría medio objeto `documents` mezclado con
    el anterior, y perder `timezone` en un update de logo sería un bug con
    consecuencias reales (cambia el "hoy" de mora y cierres).
    """
    assignments = [f"{name} = :{name}" for name in fields if name in EDITABLE_COLUMNS]
    params: dict[str, Any] = {
        name: value for name, value in fields.items() if name in EDITABLE_COLUMNS
    }
    if settings is not None:
        assignments.append("settings = cast(:settings as jsonb)")
        params["settings"] = json.dumps(settings)
    if not assignments:
        return
    params["id"] = str(company_id)
    await db.execute(
        text(f"update public.company set {', '.join(assignments)} where id = :id"),
        params,
    )


_TEMPLATE_COLUMNS = "id, document_type, name, body, layout, is_active, created_at, updated_at"


async def list_templates(
    db: AsyncSession, *, company_id: UUID, document_type: str
) -> list[Row[Any]]:
    result = await db.execute(
        text(
            f"select {_TEMPLATE_COLUMNS} from public.document_template "
            "where company_id = :company_id and document_type = :document_type "
            "order by created_at desc"
        ),
        {"company_id": str(company_id), "document_type": document_type},
    )
    return list(result.all())


async def get_template(db: AsyncSession, *, company_id: UUID, template_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_TEMPLATE_COLUMNS} from public.document_template "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(template_id)},
    )
    return result.first()


async def get_active_template(
    db: AsyncSession, *, company_id: UUID, document_type: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_TEMPLATE_COLUMNS} from public.document_template "
            "where company_id = :company_id and document_type = :document_type and is_active"
        ),
        {"company_id": str(company_id), "document_type": document_type},
    )
    return result.first()


async def insert_template(
    db: AsyncSession,
    *,
    template_id: UUID,
    company_id: UUID,
    document_type: str,
    name: str,
    body: dict[str, Any],
    layout: str,
    created_by: UUID | None,
) -> None:
    await db.execute(
        text(
            "insert into public.document_template "
            "(id, company_id, document_type, name, body, layout, created_by) "
            "values (:id, :company_id, :document_type, :name, cast(:body as jsonb), "
            "cast(:layout as document_layout), :created_by)"
        ),
        {
            "id": str(template_id),
            "company_id": str(company_id),
            "document_type": document_type,
            "name": name,
            "body": json.dumps(body),
            "layout": layout,
            "created_by": str(created_by) if created_by else None,
        },
    )


async def update_template(
    db: AsyncSession, *, company_id: UUID, template_id: UUID, fields: dict[str, Any]
) -> None:
    """`fields` viene de `DocumentTemplateUpdateIn.model_dump(exclude_unset=True)`
    en el servicio — solo puede traer `name`/`body`, nunca texto libre en la
    posición de un nombre de columna.
    """
    assignments = []
    params: dict[str, Any] = {"company_id": str(company_id), "id": str(template_id)}
    if "name" in fields:
        assignments.append("name = :name")
        params["name"] = fields["name"]
    if "body" in fields:
        assignments.append("body = cast(:body as jsonb)")
        params["body"] = json.dumps(fields["body"])
    if "layout" in fields:
        assignments.append("layout = cast(:layout as document_layout)")
        params["layout"] = fields["layout"]
    if not assignments:
        return
    await db.execute(
        text(
            f"update public.document_template set {', '.join(assignments)} "
            "where company_id = :company_id and id = :id"
        ),
        params,
    )


async def delete_template(db: AsyncSession, *, company_id: UUID, template_id: UUID) -> None:
    await db.execute(
        text("delete from public.document_template where company_id = :company_id and id = :id"),
        {"company_id": str(company_id), "id": str(template_id)},
    )


async def deactivate_active_template(
    db: AsyncSession, *, company_id: UUID, document_type: str
) -> None:
    """Paso 1 del swap de `activate_template` (service.py): desactiva la que
    esté activa hoy, si hay — SIEMPRE antes de activar la nueva, en la misma
    transacción, para que el índice único parcial nunca se viole ni en un
    punto intermedio.
    """
    await db.execute(
        text(
            "update public.document_template set is_active = false "
            "where company_id = :company_id and document_type = :document_type and is_active"
        ),
        {"company_id": str(company_id), "document_type": document_type},
    )


async def activate_template(db: AsyncSession, *, company_id: UUID, template_id: UUID) -> None:
    await db.execute(
        text(
            "update public.document_template set is_active = true "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(template_id)},
    )
