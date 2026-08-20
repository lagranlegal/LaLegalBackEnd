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
