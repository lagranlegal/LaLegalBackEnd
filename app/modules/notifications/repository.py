"""SQL del módulo de avisos.

Dos clases de consulta, y conviene no mezclarlas al leer:

- Las del **job** (resumen y despachador) corren con la sesión de bypass
  (`AsyncSessionLocal` directo), porque recorren todas las empresas. Por eso
  TODAS filtran por `company_id` explícito: RLS no las protege.
- Las de los **endpoints** corren con `get_tenant_db` y RLS encima.

Las fechas "del día" se comparan en la zona horaria de la EMPRESA
(`at time zone :tz`), nunca con `current_date` (ARCHITECTURE §10).
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

# ------------------------------------------------------------------ empresa ----


async def list_digest_companies(
    db: AsyncSession, *, only: list[UUID] | None = None
) -> list[Row[Any]]:
    """Empresas activas con suscripción vigente. Una empresa suspendida o
    vencida no recibe resumen: sus usuarios no pueden entrar a hacer nada con
    él, y el aviso que sí le servía (E8) ya salió antes de vencer."""
    result = await db.execute(
        text(
            """
            select distinct on (c.id)
                   c.id, c.name, c.contact_email, c.contact_phone, c.settings,
                   s.expires_at as subscription_expires_at
            from public.company c
            join public.subscription s on s.company_id = c.id and s.status = 'active'
            where c.status = 'active'
              and (cast(:only as uuid[]) is null or c.id = any(cast(:only as uuid[])))
            order by c.id, s.expires_at desc
            """
        ),
        {"only": [str(c) for c in only] if only is not None else None},
    )
    return list(result.all())


async def get_company(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id, name, contact_email, contact_phone, settings "
            "from public.company where id = :id"
        ),
        {"id": str(company_id)},
    )
    return result.first()


async def update_notification_settings(
    db: AsyncSession, *, company_id: UUID, value: dict[str, Any]
) -> None:
    """Reemplaza SOLO la rama `notifications` del jsonb: `settings` guarda
    también la zona horaria, que decide el "hoy" de mora y cierres, y pisarla
    al guardar una preferencia de correo sería un bug silencioso."""
    await db.execute(
        text(
            """
            update public.company
            set settings = jsonb_set(coalesce(settings, '{}'::jsonb), '{notifications}',
                                     cast(:value as jsonb), true)
            where id = :id
            """
        ),
        {"id": str(company_id), "value": json.dumps(value)},
    )


async def list_digest_recipients(db: AsyncSession, *, company_id: UUID) -> list[Row[Any]]:
    """Usuarios ACTIVOS cuyo rol tiene `notifications.receive_digest` (§4.3:
    el destinatario lo decide un permiso, no una columna)."""
    result = await db.execute(
        text(
            """
            select u.id, u.full_name, u.email
            from public.app_user u
            join public.role_permission rp on rp.role_id = u.role_id
            join public.permission p on p.id = rp.permission_id
                                    and p.code = 'notifications.receive_digest'
            where u.company_id = :company_id and u.status = 'active'
            order by u.email
            """
        ),
        {"company_id": str(company_id)},
    )
    return list(result.all())


# ----------------------------------------------------------- eventos/entregas ----


async def insert_event(
    db: AsyncSession,
    *,
    company_id: UUID,
    event_type: str,
    audience: str,
    dedupe_key: str,
    occurred_on: date,
    payload: dict[str, Any],
    customer_id: UUID | None,
    entity_type: str | None,
    entity_id: UUID | None,
    target_date: date | None,
) -> UUID | None:
    """`on conflict do nothing` (§6.2): para el job, que la llave ya exista es
    el camino NORMAL — el hecho ya se registró. Devuelve None en ese caso."""
    result = await db.execute(
        text(
            """
            insert into public.notification_event
                (company_id, event_type, audience, customer_id, entity_type, entity_id,
                 payload, dedupe_key, occurred_on, target_date)
            values (:company_id, :event_type, :audience, :customer_id, :entity_type, :entity_id,
                    cast(:payload as jsonb), :dedupe_key, :occurred_on, :target_date)
            on conflict (company_id, dedupe_key) do nothing
            returning id
            """
        ),
        {
            "company_id": str(company_id),
            "event_type": event_type,
            "audience": audience,
            "customer_id": str(customer_id) if customer_id else None,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "payload": json.dumps(payload),
            "dedupe_key": dedupe_key,
            "occurred_on": occurred_on,
            "target_date": target_date,
        },
    )
    return result.scalar_one_or_none()


async def event_exists(db: AsyncSession, *, company_id: UUID, dedupe_key: str) -> bool:
    result = await db.execute(
        text(
            "select 1 from public.notification_event "
            "where company_id = :company_id and dedupe_key = :dedupe_key"
        ),
        {"company_id": str(company_id), "dedupe_key": dedupe_key},
    )
    return result.first() is not None


async def insert_delivery(
    db: AsyncSession,
    *,
    company_id: UUID,
    event_id: UUID,
    to_address: str | None,
    recipient_user_id: UUID | None,
    status: str,
    last_error: str | None = None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.notification_delivery
                (company_id, event_id, channel, to_address, recipient_user_id, status, last_error)
            values (:company_id, :event_id, 'email', :to_address, :recipient_user_id, :status,
                    :last_error)
            on conflict do nothing
            """
        ),
        {
            "company_id": str(company_id),
            "event_id": str(event_id),
            "to_address": to_address,
            "recipient_user_id": str(recipient_user_id) if recipient_user_id else None,
            "status": status,
            "last_error": last_error,
        },
    )


async def last_event_day(
    db: AsyncSession, *, company_id: UUID, event_types: list[str]
) -> date | None:
    result = await db.execute(
        text(
            "select max(occurred_on) from public.notification_event "
            "where company_id = :company_id and event_type in :types"
        ).bindparams(bindparam("types", expanding=True)),
        {"company_id": str(company_id), "types": event_types},
    )
    value: date | None = result.scalar_one_or_none()
    return value


async def get_customer_contact(
    db: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id, full_name, email from public.customer "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(customer_id)},
    )
    return result.first()


# ---------------------------------------------------- insumos del resumen (E*) ----


async def activity_totals(
    db: AsyncSession, *, company_id: UUID, tz: str, date_from: date, date_to: date
) -> dict[str, Any]:
    """Movimiento del período, por día LOCAL de la empresa. Un contrato
    importado (`legacy_code`) o nacido de una ampliación no es un contrato
    nuevo del día: es carga histórica o la continuación de otro."""
    params = {"cid": str(company_id), "tz": tz, "d0": date_from, "d1": date_to}
    row = (
        await db.execute(
            text(
                """
                select
                  (select count(*) from public.contract
                    where company_id = :cid and legacy_code is null
                      and parent_contract_id is null
                      and (created_at at time zone :tz)::date between :d0 and :d1)
                    as contracts_created,
                  (select coalesce(sum(principal), 0) from public.contract
                    where company_id = :cid and legacy_code is null
                      and parent_contract_id is null
                      and (created_at at time zone :tz)::date between :d0 and :d1)
                    as contracts_amount,
                  (select count(*) from public.contract_payment
                    where company_id = :cid
                      and (paid_at at time zone :tz)::date between :d0 and :d1) as payments,
                  (select coalesce(sum(total), 0) from public.contract_payment
                    where company_id = :cid
                      and (paid_at at time zone :tz)::date between :d0 and :d1)
                    as payments_amount,
                  (select count(*) from public.sale
                    where company_id = :cid and status <> 'voided'
                      and (sold_at at time zone :tz)::date between :d0 and :d1) as sales,
                  (select coalesce(sum(total), 0) from public.sale
                    where company_id = :cid and status <> 'voided'
                      and (sold_at at time zone :tz)::date between :d0 and :d1) as sales_amount,
                  (select count(*) from public.sale
                    where company_id = :cid and status = 'voided'
                      and (updated_at at time zone :tz)::date between :d0 and :d1)
                    as sales_voided
                """
            ),
            params,
        )
    ).one()
    m = row._mapping
    return {
        "contracts_created": int(m["contracts_created"]),
        "contracts_amount": str(Decimal(m["contracts_amount"])),
        "payments": int(m["payments"]),
        "payments_amount": str(Decimal(m["payments_amount"])),
        "sales": int(m["sales"]),
        "sales_amount": str(Decimal(m["sales_amount"])),
        "sales_voided": int(m["sales_voided"]),
    }


async def unclosed_sessions(db: AsyncSession, *, company_id: UUID, today: date) -> list[Row[Any]]:
    """E3: turnos de días ANTERIORES que siguen abiertos. Se notifica la
    ausencia del cierre, no el cierre (§3)."""
    result = await db.execute(
        text(
            """
            select id, session_date from public.cash_session
            where company_id = :cid and status = 'open' and session_date < :today
            order by session_date
            """
        ),
        {"cid": str(company_id), "today": today},
    )
    return list(result.all())


async def cash_differences(
    db: AsyncSession, *, company_id: UUID, tz: str, date_from: date, date_to: date
) -> list[Row[Any]]:
    """E4: cierres con diferencia en el período. TODOS, no solo los que pasan
    el umbral (§12.2-4): el umbral solo marca cuáles merecerían alerta."""
    result = await db.execute(
        text(
            """
            select id, session_date, difference, difference_reason
            from public.cash_session
            where company_id = :cid and status = 'closed'
              and difference is not null and difference <> 0
              and (closed_at at time zone :tz)::date between :d0 and :d1
            order by closed_at
            """
        ),
        {"cid": str(company_id), "tz": tz, "d0": date_from, "d1": date_to},
    )
    return list(result.all())


async def discounts(
    db: AsyncSession, *, company_id: UUID, tz: str, date_from: date, date_to: date
) -> list[Row[Any]]:
    result = await db.execute(
        text(
            """
            select 'payment' as kind, receipt_number as number, discount_amount as amount,
                   paid_at as at
            from public.contract_payment
            where company_id = :cid and discount_amount > 0
              and (paid_at at time zone :tz)::date between :d0 and :d1
            union all
            select 'sale', number, discount_amount, sold_at
            from public.sale
            where company_id = :cid and discount_amount > 0
              and (sold_at at time zone :tz)::date between :d0 and :d1
            order by at
            """
        ),
        {"cid": str(company_id), "tz": tz, "d0": date_from, "d1": date_to},
    )
    return list(result.all())


async def dead_deliveries_count(
    db: AsyncSession, *, company_id: UUID, tz: str, date_from: date, date_to: date
) -> int:
    result = await db.execute(
        text(
            """
            select count(*) from public.notification_delivery
            where company_id = :cid and status = 'dead'
              and (updated_at at time zone :tz)::date between :d0 and :d1
            """
        ),
        {"cid": str(company_id), "tz": tz, "d0": date_from, "d1": date_to},
    )
    return int(result.scalar_one())


# --------------------------------------------------------------- despachador ----


async def claim_due_deliveries(
    db: AsyncSession, *, now: datetime, limit: int, only: list[UUID] | None = None
) -> list[Row[Any]]:
    """Toma las entregas cuya hora llegó y las pasa a `sending` en la MISMA
    sentencia: dos despachadores concurrentes nunca toman la misma fila
    (`for update skip locked`)."""
    result = await db.execute(
        text(
            """
            with due as (
              select id from public.notification_delivery
              where status in ('pending', 'failed') and scheduled_at <= :now
                and (cast(:only as uuid[]) is null or company_id = any(cast(:only as uuid[])))
              order by scheduled_at
              limit :limit
              for update skip locked
            )
            update public.notification_delivery d
            set status = 'sending'
            from due
            where d.id = due.id
            returning d.id, d.company_id, d.event_id, d.to_address, d.attempts
            """
        ),
        {
            "now": now,
            "limit": limit,
            "only": [str(c) for c in only] if only is not None else None,
        },
    )
    return list(result.all())


async def release_stuck_sending(db: AsyncSession, *, older_than: datetime) -> int:
    """Una entrega que quedó en `sending` es un proceso que murió entre el
    envío y el registro. Se devuelve a `failed` para que el barrido la retome;
    reenviar es seguro porque la llave de idempotencia de Resend es la entrega."""
    result = await db.execute(
        text(
            """
            update public.notification_delivery
            set status = 'failed', last_error = 'quedó en sending: el proceso se interrumpió'
            where status = 'sending' and updated_at < :older_than
            """
        ),
        {"older_than": older_than},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def get_event(db: AsyncSession, *, event_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select id, company_id, event_type, audience, customer_id, payload, occurred_on,
                   target_date
            from public.notification_event where id = :id
            """
        ),
        {"id": str(event_id)},
    )
    return result.first()


async def count_sent_to(
    db: AsyncSession, *, company_id: UUID, to_address: str, since: datetime
) -> int:
    """Correos que YA salieron a esa dirección desde `since` — el insumo del
    tope de la Ley 2300. Por empresa: cada compraventa es un acreedor distinto
    (§12.2-6) y responde por sus propios contactos."""
    result = await db.execute(
        text(
            """
            select count(*) from public.notification_delivery d
            join public.notification_event e on e.id = d.event_id
            where d.company_id = :cid and d.channel = 'email'
              and lower(d.to_address) = lower(:to_address)
              and e.audience = 'customer'
              and d.sent_at >= :since
              and d.status in ('sent', 'delivered')
            """
        ),
        {"cid": str(company_id), "to_address": to_address, "since": since},
    )
    return int(result.scalar_one())


async def update_delivery(
    db: AsyncSession,
    *,
    delivery_id: UUID,
    status: str,
    attempts: int | None = None,
    last_error: str | None = None,
    provider_id: str | None = None,
    scheduled_at: datetime | None = None,
    sent_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            """
            update public.notification_delivery
            set status = :status,
                attempts = coalesce(:attempts, attempts),
                last_error = :last_error,
                provider_id = coalesce(:provider_id, provider_id),
                scheduled_at = coalesce(:scheduled_at, scheduled_at),
                sent_at = coalesce(:sent_at, sent_at)
            where id = :id
            """
        ),
        {
            "id": str(delivery_id),
            "status": status,
            "attempts": attempts,
            "last_error": last_error,
            "provider_id": provider_id,
            "scheduled_at": scheduled_at,
            "sent_at": sent_at,
        },
    )


# ------------------------------------------------------------------ endpoints ----


async def list_deliveries(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
    status: str | None,
    event_type: str | None,
) -> list[Row[Any]]:
    query = """
        select d.id, d.event_id, e.event_type, e.audience, e.occurred_on, d.channel,
               d.to_address, d.recipient_user_id, d.status, d.attempts, d.last_error,
               d.provider_id, d.scheduled_at, d.sent_at, d.created_at, d.updated_at
        from public.notification_delivery d
        join public.notification_event e on e.id = d.event_id
        where d.company_id = :company_id
    """
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if status is not None:
        query += " and d.status = :status"
        params["status"] = status
    if event_type is not None:
        query += " and e.event_type = :event_type"
        params["event_type"] = event_type
    if cursor is not None:
        query += " and (d.created_at, d.id) < (:cursor_at, :cursor_id)"
        params["cursor_at"] = cursor[0]
        params["cursor_id"] = str(cursor[1])
    query += " order by d.created_at desc, d.id desc limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())
