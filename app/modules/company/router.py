from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.company import service
from app.modules.company.schemas import (
    CompanySettingsOut,
    CompanySettingsUpdateIn,
    DocumentTemplateCreateIn,
    DocumentTemplateOut,
    DocumentTemplateUpdateIn,
    DocumentType,
)

router = APIRouter(prefix="/api/v1/company", tags=["company"])

_configure = require_permission("company.configure")
# La LECTURA de la plantilla activa la necesita cualquiera que pueda
# imprimir un contrato — no solo quien lo configura. `ContractDetailPage`
# está gateado por `contracts.view`, no por `company.configure`: si este
# endpoint exigiera `company.configure`, un asesor sin ese permiso se
# quedaría sin poder imprimir en cuanto una empresa active una plantilla.
# Mismo criterio que ya usan header_note/legal_notice, que salen de `GET
# /me` (accesible a cualquiera), no de `GET /company/settings`.
_read_active_template = require_permission("contracts.view")


@router.get("/settings", response_model=CompanySettingsOut)
async def get_settings(
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CompanySettingsOut:
    return await service.get_settings(db, company_id=user.company_id)


@router.patch("/settings", response_model=CompanySettingsOut)
async def update_settings(
    body: CompanySettingsUpdateIn,
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CompanySettingsOut:
    return await service.update_settings(
        db, company_id=user.company_id, body=body, actor_id=user.id
    )


@router.get("/document-templates", response_model=list[DocumentTemplateOut])
async def list_document_templates(
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    document_type: Annotated[DocumentType, Query()],
) -> list[DocumentTemplateOut]:
    return await service.list_templates(db, company_id=user.company_id, document_type=document_type)


@router.get("/document-templates/active", response_model=DocumentTemplateOut | None)
async def get_active_document_template(
    user: Annotated[CurrentUser, Depends(_read_active_template)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    document_type: Annotated[DocumentType, Query()],
) -> DocumentTemplateOut | None:
    return await service.get_active_template(
        db, company_id=user.company_id, document_type=document_type
    )


@router.post("/document-templates", response_model=DocumentTemplateOut, status_code=201)
async def create_document_template(
    body: DocumentTemplateCreateIn,
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> DocumentTemplateOut:
    return await service.create_template(
        db, company_id=user.company_id, body=body, actor_id=user.id
    )


@router.patch("/document-templates/{template_id}", response_model=DocumentTemplateOut)
async def update_document_template(
    template_id: UUID,
    body: DocumentTemplateUpdateIn,
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> DocumentTemplateOut:
    return await service.update_template(
        db, company_id=user.company_id, template_id=template_id, body=body, actor_id=user.id
    )


@router.delete("/document-templates/{template_id}", status_code=204)
async def delete_document_template(
    template_id: UUID,
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    await service.delete_template(
        db, company_id=user.company_id, template_id=template_id, actor_id=user.id
    )


@router.post("/document-templates/{template_id}/activate", response_model=DocumentTemplateOut)
async def activate_document_template(
    template_id: UUID,
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> DocumentTemplateOut:
    return await service.activate_template(
        db, company_id=user.company_id, template_id=template_id, actor_id=user.id
    )
