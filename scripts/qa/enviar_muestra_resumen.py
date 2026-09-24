"""Manda UNA muestra del resumen semanal de la empresa de laboratorio `ZZ QA` a un buzón real.

Sirve para ver cómo se ve el correo y si cae en spam, SIN encender las notificaciones de
ninguna empresa: arma el resumen en una transacción de SOLO LECTURA (no registra eventos ni
entregas) y lo manda directo con el proveedor. Corre DENTRO de la máquina de la API, que es la
que tiene `RESEND_API_KEY`; la imagen solo trae `app/`, así que se sube a mano:

    flyctl ssh sftp shell -a compraventa-backend-dev
      » put scripts/qa/enviar_muestra_resumen.py /tmp/muestra.py     (y Ctrl+D para salir)
    flyctl ssh console -a compraventa-backend-dev -C "sh -c 'cd /app && python /tmp/muestra.py'"
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.db import AsyncSessionLocal
from app.modules.notifications import catalog, digest, preferences, repository, templates
from app.modules.notifications.providers import EmailMessage, get_default_provider

TO = "mateojaras@gmail.com"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        companies = await repository.list_digest_companies(db, only=None)
    zz = [c for c in companies if c._mapping["name"].startswith("ZZ QA —")]
    assert len(zz) == 1, [c._mapping["name"] for c in companies]
    m = zz[0]._mapping
    settings = m["settings"] or {}
    tz = settings.get("timezone") or digest.DEFAULT_TIMEZONE
    today = digest.today_in(tz, now=datetime.now(UTC))
    async with AsyncSessionLocal() as db, db.begin():
        await db.execute(text("set transaction read only"))
        payload, alerts, activity, ready = await digest._sections(
            db,
            company_id=m["id"],
            tz=tz,
            today=today,
            after=today - timedelta(days=7),
            prefs=preferences.parse(settings),
            expires_at=m["subscription_expires_at"],
            weekly=True,
        )
    branding = templates.Branding(
        company_name=m["name"], contact_email=m["contact_email"], contact_phone=m["contact_phone"]
    )
    r = templates.render_digest(catalog.WEEKLY_DIGEST, payload, branding)
    print(
        "empresa:",
        m["name"],
        "| alertas:",
        alerts,
        "| actividad:",
        activity,
        "| listos:",
        len(ready),
    )
    print("asunto:", r.subject)
    res = await get_default_provider().send(
        EmailMessage(
            from_header=templates.from_header(r.from_name, "notificaciones@prendo.com.co"),
            to=TO,
            subject="[MUESTRA] " + r.subject,
            html=r.html,
            text=r.text,
        )
    )
    print("ok:", res.ok, "id:", res.provider_id, "error:", res.error)


asyncio.run(main())
