"""Lo que otros módulos pueden pedirle a `customers` (CLAUDE.md regla 2).

Hoy, la base legal del correo del cliente (docs/NOTIFICACIONES.md §9.2):

- `contracts` la escribe cuando nace un contrato vivo (§9.2-a), y registra
  el correo y la casilla de autorización que se capturan en el formulario de
  crear contrato (§9.2-f, origen `contract_form`).
- `notifications` registra la baja que el titular pidió por el enlace del
  correo (§9.2-e) y lee lo necesario para mostrarle la página de baja.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers import repository
from app.modules.customers.repository import NOW
from app.modules.identity import repository as identity_repo

#: Origen de la autorización marcada en el formulario de crear contrato
#: (NOTIFICACIONES §9.2-f). La de la ficha del cliente es `counter`.
_CONTRACT_FORM = "contract_form"


async def ensure_contract_basis(db: AsyncSession, *, company_id: UUID, customer_id: UUID) -> bool:
    """Base `contract` para un cliente que acaba de quedar con un contrato
    vivo, si tiene correo y todavía no tiene base. Se llama en la MISMA
    transacción que crea el contrato.

    **Se escribe en vez de deducirse en cada envío** (§9.2-a): la base que
    importa es la que había el día que salió el correo, y un `join` al vuelo
    contesta qué pasa hoy, no qué pasaba entonces.

    No se audita aparte: el hecho que la origina (crear, importar o ampliar
    el contrato) ya queda en `audit_log`, y la base es su consecuencia. Lo que
    sí se audita es lo que decide una PERSONA — la casilla del mostrador y la
    baja."""
    return await repository.set_contract_basis_if_missing(
        db, company_id=company_id, customer_id=customer_id
    )


async def get_email_status(
    db: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> dict[str, Any] | None:
    """Correo y baja del cliente, o None si no existe en esa empresa."""
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    if row is None:
        return None
    m = row._mapping
    return {"email": m["email"], "email_opt_out_at": m["email_opt_out_at"]}


async def record_opt_out_from_link(
    db: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> datetime | None:
    """La baja pedida por el titular desde el enlace del correo.

    Idempotente: si ya estaba de baja, devuelve la fecha original y no
    audita otra vez — un segundo POST no es un hecho nuevo. `user_id` va
    NULL en `audit_log`: no la hizo un usuario de la empresa, la hizo la
    persona, y confundir las dos cosas sería decir que alguien del mostrador
    la dio de baja."""
    changed, opted_out_at = await repository.mark_opted_out(
        db, company_id=company_id, customer_id=customer_id
    )
    if changed:
        await identity_repo.insert_audit_log(
            db,
            company_id=company_id,
            user_id=None,
            module="customers",
            action="email_opt_out",
            entity_type="customer",
            entity_id=customer_id,
            before={"email_opt_out_at": None},
            after={"email_opt_out_at": str(opted_out_at), "source": "link"},
        )
    return opted_out_at


def _invalid(field: str, msg: str) -> RequestValidationError:
    """El mismo contrato de error que un campo mal formado: `422
    VALIDATION_ERROR` con el campo en `details.errors[].loc`, para que el
    formulario lo pinte debajo de la casilla que corresponde."""
    return RequestValidationError(
        [{"type": "value_error", "loc": ("body", field), "msg": msg, "input": None}]
    )


def _clean(email: str | None) -> str | None:
    return (email or "").strip() or None


async def check_contract_form_email(
    db: AsyncSession,
    *,
    company_id: UUID,
    customer_id: UUID,
    email: str | None,
    consent: bool | None,
) -> None:
    """Valida, ANTES de mover plata, lo que el formulario del contrato quiere
    escribir en la ficha del cliente. Separado de `record_...` para que el
    rechazo llegue antes que cualquier otra validación del contrato: quien
    está en el mostrador corrige una casilla, no rehace el préstamo.

    Dos reglas:
    - **El correo solo llena un vacío.** Si ya tiene OTRO, cambiarlo es una
      edición de la ficha (con su `before` auditado y su efecto sobre el
      rebote), no un efecto lateral de crear un contrato.
    - **La casilla exige correo.** Mismo criterio que el formulario del
      cliente: autorizar a escribirle a una dirección que no existe no es una
      autorización de nada.
    """
    if not email and not consent:
        return
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    if row is None:
        return  # el contrato ya responde 404 por el cliente
    current = _clean(row._mapping["email"])
    new = _clean(email)
    if new and current and new.lower() != current.lower():
        raise _invalid(
            "customer_email",
            "El cliente ya tiene otro correo. Para cambiarlo, edítalo en su ficha.",
        )
    if consent and not (current or new):
        raise _invalid(
            "customer_email_consent",
            "Para registrar la autorización, el cliente necesita un correo.",
        )


async def record_contract_form_email(
    db: AsyncSession,
    *,
    company_id: UUID,
    customer_id: UUID,
    email: str | None,
    consent: bool | None,
    acting_user_id: UUID,
) -> None:
    """Escribe en la ficha el correo y la autorización capturados al crear el
    contrato, en la MISMA transacción (CLAUDE.md regla 4). Se llama después de
    `check_contract_form_email` y ANTES de `ensure_contract_basis`: así un
    correo recién cargado sin casilla queda con base `contract` (la escribe
    esa función), y con casilla queda `consent`, que `ensure_contract_basis`
    nunca pisa.

    Se audita como `update_customer`, igual que la casilla de la ficha: es lo
    que decide una PERSONA (§7) y la prueba de «¿quién dijo que se le podía
    escribir, y cuándo?». Lo que distingue el origen es
    `email_consent_source = 'contract_form'`, que queda en el `after`.
    """
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    if row is None:
        return
    m = row._mapping
    fields: dict[str, Any] = {}
    new = _clean(email)
    if new and not _clean(m["email"]):
        fields["email"] = new
    # Si ya tenía `consent`, se conserva la fecha original: es la prueba.
    if consent and m["email_basis"] != "consent":
        fields.update(
            email_basis="consent",
            email_basis_at=NOW,
            email_consent_at=NOW,
            email_consent_source=_CONTRACT_FORM,
        )
    if not fields:
        return
    await repository.update_customer(
        db, company_id=company_id, customer_id=customer_id, fields=fields
    )
    after_row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    assert after_row is not None
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="customers",
        action="update_customer",
        entity_type="customer",
        entity_id=customer_id,
        before={k: (str(m[k]) if m[k] is not None else None) for k in fields},
        after={
            k: (str(after_row._mapping[k]) if after_row._mapping[k] is not None else None)
            for k in fields
        },
    )
