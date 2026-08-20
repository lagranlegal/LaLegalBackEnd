from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.company import repository
from app.modules.company.schemas import (
    CompanySettingsOut,
    CompanySettingsUpdateIn,
    DocumentSettingsOut,
)
from app.modules.identity import repository as identity_repo

_DEFAULT_TIMEZONE = "America/Bogota"
_DEFAULT_CURRENCY = "COP"


def _row_to_settings(row: Row[Any]) -> CompanySettingsOut:
    m = row._mapping
    settings = m["settings"] or {}
    documents = settings.get("documents") or {}
    return CompanySettingsOut(
        id=m["id"],
        name=m["name"],
        legal_name=m["legal_name"],
        tax_id=m["tax_id"],
        contact_email=m["contact_email"],
        contact_phone=m["contact_phone"],
        address=m["address"],
        logo_url=m["logo_url"],
        signature_url=m["signature_url"],
        timezone=settings.get("timezone", _DEFAULT_TIMEZONE),
        currency=settings.get("currency", _DEFAULT_CURRENCY),
        documents=DocumentSettingsOut(
            header_note=documents.get("header_note"),
            footer_note=documents.get("footer_note"),
            legal_notice=documents.get("legal_notice"),
        ),
    )


async def get_settings(db: AsyncSession, *, company_id: UUID) -> CompanySettingsOut:
    row = await repository.get_company(db, company_id=company_id)
    if row is None:
        raise NotFoundError("La empresa no existe.")
    return _row_to_settings(row)


async def update_settings(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: CompanySettingsUpdateIn,
    actor_id: UUID,
) -> CompanySettingsOut:
    row = await repository.get_company(db, company_id=company_id)
    if row is None:
        raise NotFoundError("La empresa no existe.")

    fields = body.model_dump(exclude_unset=True)
    documents_patch = fields.pop("documents", None)

    # Fusión explícita del jsonb, no un `||` a ciegas: `settings` guarda
    # también `timezone`, `currency` y `grace_days`, y perder cualquiera de
    # esos al guardar un pie de página sería un bug silencioso — la zona
    # horaria decide el "hoy" con el que se calculan mora y cierres.
    merged_settings: dict[str, Any] | None = None
    if documents_patch is not None:
        current = dict(row._mapping["settings"] or {})
        current_documents = dict(current.get("documents") or {})
        current_documents.update(documents_patch)
        current["documents"] = current_documents
        merged_settings = current

    await repository.update_company(
        db, company_id=company_id, fields=fields, settings=merged_settings
    )

    # La firma de la empresa se estampa en documentos legales y el logo/los
    # textos salen impresos a nombre de la compraventa: cambiarlos es una
    # acción sensible (CLAUDE.md regla 6). Se audita QUÉ campos cambiaron, no
    # su contenido — un `legal_notice` de 1000 caracteres no aporta nada en el
    # log y lo vuelve ilegible.
    changed = sorted([*fields.keys(), *(["documents"] if documents_patch is not None else [])])
    if changed:
        await identity_repo.insert_audit_log(
            db,
            company_id=company_id,
            user_id=actor_id,
            module="company",
            action="update_settings",
            entity_type="company",
            entity_id=company_id,
            after={"changed_fields": changed},
        )

    updated = await repository.get_company(db, company_id=company_id)
    assert updated is not None
    return _row_to_settings(updated)
