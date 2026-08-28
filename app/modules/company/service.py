from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.company import repository
from app.modules.company.schemas import (
    CompanySettingsOut,
    CompanySettingsUpdateIn,
    DocumentSettingsOut,
    DocumentTemplateCreateIn,
    DocumentTemplateOut,
    DocumentTemplateUpdateIn,
)
from app.modules.identity import repository as identity_repo

_DEFAULT_TIMEZONE = "America/Bogota"
_DEFAULT_CURRENCY = "COP"
_DEFAULT_RETURN_WINDOW_DAYS = 30


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
        return_window_days=settings.get("return_window_days", _DEFAULT_RETURN_WINDOW_DAYS),
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
    return_window_days_patch = fields.pop("return_window_days", None)

    # Fusión explícita del jsonb, no un `||` a ciegas: `settings` guarda
    # también `timezone`, `currency` y `grace_days`, y perder cualquiera de
    # esos al guardar un pie de página sería un bug silencioso — la zona
    # horaria decide el "hoy" con el que se calculan mora y cierres.
    merged_settings: dict[str, Any] | None = None
    if documents_patch is not None or return_window_days_patch is not None:
        current = dict(row._mapping["settings"] or {})
        if documents_patch is not None:
            current_documents = dict(current.get("documents") or {})
            current_documents.update(documents_patch)
            current["documents"] = current_documents
        if return_window_days_patch is not None:
            current["return_window_days"] = return_window_days_patch
        merged_settings = current

    await repository.update_company(
        db, company_id=company_id, fields=fields, settings=merged_settings
    )

    # La firma de la empresa se estampa en documentos legales y el logo/los
    # textos salen impresos a nombre de la compraventa: cambiarlos es una
    # acción sensible (CLAUDE.md regla 6). Se audita QUÉ campos cambiaron, no
    # su contenido — un `legal_notice` de 1000 caracteres no aporta nada en el
    # log y lo vuelve ilegible.
    changed = sorted(
        [
            *fields.keys(),
            *(["documents"] if documents_patch is not None else []),
            *(["return_window_days"] if return_window_days_patch is not None else []),
        ]
    )
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


def _row_to_template(row: Row[Any]) -> DocumentTemplateOut:
    m = row._mapping
    return DocumentTemplateOut(
        id=m["id"],
        document_type=m["document_type"],
        name=m["name"],
        body=m["body"],
        is_active=m["is_active"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


async def list_templates(
    db: AsyncSession, *, company_id: UUID, document_type: str
) -> list[DocumentTemplateOut]:
    rows = await repository.list_templates(db, company_id=company_id, document_type=document_type)
    return [_row_to_template(r) for r in rows]


async def get_active_template(
    db: AsyncSession, *, company_id: UUID, document_type: str
) -> DocumentTemplateOut | None:
    row = await repository.get_active_template(
        db, company_id=company_id, document_type=document_type
    )
    return _row_to_template(row) if row is not None else None


async def create_template(
    db: AsyncSession, *, company_id: UUID, body: DocumentTemplateCreateIn, actor_id: UUID
) -> DocumentTemplateOut:
    template_id = uuid4()
    await repository.insert_template(
        db,
        template_id=template_id,
        company_id=company_id,
        document_type=body.document_type,
        name=body.name,
        body=body.body,
        created_by=actor_id,
    )
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="company",
        action="create_document_template",
        entity_type="document_template",
        entity_id=template_id,
        after={"document_type": body.document_type, "name": body.name},
    )
    row = await repository.get_template(db, company_id=company_id, template_id=template_id)
    assert row is not None
    return _row_to_template(row)


async def update_template(
    db: AsyncSession,
    *,
    company_id: UUID,
    template_id: UUID,
    body: DocumentTemplateUpdateIn,
    actor_id: UUID,
) -> DocumentTemplateOut:
    existing = await repository.get_template(db, company_id=company_id, template_id=template_id)
    if existing is None:
        raise NotFoundError("La plantilla no existe.")

    fields = body.model_dump(exclude_unset=True)
    if fields:
        await repository.update_template(
            db, company_id=company_id, template_id=template_id, fields=fields
        )
        await identity_repo.insert_audit_log(
            db,
            company_id=company_id,
            user_id=actor_id,
            module="company",
            action="update_document_template",
            entity_type="document_template",
            entity_id=template_id,
            after={"changed_fields": sorted(fields.keys())},
        )

    row = await repository.get_template(db, company_id=company_id, template_id=template_id)
    assert row is not None
    return _row_to_template(row)


async def delete_template(
    db: AsyncSession, *, company_id: UUID, template_id: UUID, actor_id: UUID
) -> None:
    existing = await repository.get_template(db, company_id=company_id, template_id=template_id)
    if existing is None:
        raise NotFoundError("La plantilla no existe.")
    if existing._mapping["is_active"]:
        # Borrarla dejaría el documento sin nada que renderizar. Activar otra
        # (o ninguna, cae al JSX de respaldo) es un paso explícito distinto.
        raise ConflictError(
            "No se puede eliminar la plantilla activa. Activa otra primero.",
            code="TEMPLATE_IS_ACTIVE",
        )
    await repository.delete_template(db, company_id=company_id, template_id=template_id)
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="company",
        action="delete_document_template",
        entity_type="document_template",
        entity_id=template_id,
        after={
            "document_type": existing._mapping["document_type"],
            "name": existing._mapping["name"],
        },
    )


async def activate_template(
    db: AsyncSession, *, company_id: UUID, template_id: UUID, actor_id: UUID
) -> DocumentTemplateOut:
    existing = await repository.get_template(db, company_id=company_id, template_id=template_id)
    if existing is None:
        raise NotFoundError("La plantilla no existe.")

    # Swap en dos pasos, misma transacción: desactivar la que esté activa HOY
    # antes de activar la nueva — en ese orden el índice único parcial nunca
    # se viola en ningún punto intermedio. Es un reemplazo (radio-button), no
    # un conflicto que el usuario deba resolver a mano.
    await repository.deactivate_active_template(
        db, company_id=company_id, document_type=existing._mapping["document_type"]
    )
    await repository.activate_template(db, company_id=company_id, template_id=template_id)

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="company",
        action="activate_document_template",
        entity_type="document_template",
        entity_id=template_id,
        after={
            "document_type": existing._mapping["document_type"],
            "name": existing._mapping["name"],
        },
    )

    row = await repository.get_template(db, company_id=company_id, template_id=template_id)
    assert row is not None
    return _row_to_template(row)
