"""Función de integración que usa `contracts.service.auction_contract` para
Rematar (CLAUDE.md regla 2: un módulo no importa el `service` de otro).
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.catalogs import repository as catalogs_repo
from app.modules.inventory import repository, rules


@dataclass(frozen=True)
class AuctionItemInput:
    contract_item_id: UUID
    category_id: UUID  # nivel 3 (lo único que guarda contract_item)
    description: str
    appraisal: Decimal | None


async def create_draft_items_from_auction(
    db: AsyncSession,
    *,
    company_id: UUID,
    items: list[AuctionItemInput],
    total_cost: Decimal,
    source_contract_id: UUID,
    created_by: UUID | None,
) -> dict[UUID, UUID]:
    """Crea un `inventory_item` en `draft` por cada prenda del contrato
    rematado (`origin='auction'`), repartiendo `total_cost` con
    `inventory.rules.split_cost_by_appraisal`. Devuelve
    `{contract_item_id: inventory_item_id}` para que `contracts.service`
    guarde el vínculo bidireccional.
    """
    if not items:
        raise AppError("El contrato no tiene artículos para rematar.")

    shares = rules.split_cost_by_appraisal(total_cost, [i.appraisal for i in items])

    entry_id = uuid4()
    entry_number = await repository.next_counter(db, company_id=company_id, prefix="INV_ENTRY")
    # La entrada se inserta ANTES que sus líneas (FK inventory_entry_line ->
    # inventory_entry) — mismo bug real que se encontró y corrigió en
    # inventory.service.create_entry.
    await repository.insert_entry(
        db,
        entry_id=entry_id,
        company_id=company_id,
        number=entry_number,
        origin_type="auction",
        supplier_id=None,
        supplier_invoice=None,
        contract_id=source_contract_id,
        total_cost=total_cost,
        notes=None,
        registered_by=created_by,
    )

    result: dict[UUID, UUID] = {}
    for auction_item, cost in zip(items, shares, strict=True):
        chain = await catalogs_repo.get_ancestor_chain(
            db, company_id=company_id, level3_category_id=auction_item.category_id
        )
        if chain is None:
            raise AppError(
                "No se pudo resolver la categoría del artículo a rematar.",
                details={"category_id": str(auction_item.category_id)},
            )
        cat1_id, cat2_id, cat3_id = chain
        # Producto ÚNICO por pieza rematada: ese anillo, de ese contrato, no
        # es "otro lote" de nada y nunca debe agrupar con otra pieza.
        product_id = uuid4()
        await repository.insert_product(
            db,
            product_id=product_id,
            company_id=company_id,
            name=auction_item.description,
            cat1_id=cat1_id,
            cat2_id=cat2_id,
            cat3_id=cat3_id,
            description=auction_item.description,
            is_unique=True,
        )

        item_id = uuid4()
        await repository.insert_item(
            db,
            item_id=item_id,
            company_id=company_id,
            product_id=product_id,
            lot_number=1,
            origin="auction",
            supplier_id=None,
            source_contract_id=source_contract_id,
            cost=cost,
            quantity=1,
            photos=[],
            created_by=created_by,
        )
        await repository.insert_entry_line(
            db,
            line_id=uuid4(),
            company_id=company_id,
            entry_id=entry_id,
            item_id=item_id,
            quantity=1,
            unit_cost=cost,
        )

        result[auction_item.contract_item_id] = item_id

    return result
