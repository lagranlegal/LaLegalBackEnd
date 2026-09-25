"""La invitación de usuario (P1) sale por NUESTRO correo (docs/NOTIFICACIONES.md §16).

Contra Postgres real. Lo que se prueba es la costura completa:

- La fila (evento + entrega `pending`) va en la transacción de la invitación;
  el envío va DESPUÉS del commit, en un `BackgroundTasks` (§5.1).
- El enlace del correo es el de la app (`/auth/callback?token_hash=…`), nunca
  el `action_link` de GoTrue, y el token NO queda guardado en ninguna fila.
- El job es la red: si el envío inmediato falló, el despachador pide un enlace
  NUEVO a Supabase (el viejo ya venció o nunca salió) y lo manda.
- Sin proveedor (o sin `FRONTEND_URL`) la invitación NO queda muda: la manda
  Supabase, como antes.
- El interruptor de avisos de la empresa (apagado por defecto) no la toca.

**Nada sale a la red:** Supabase Auth se reemplaza por un doble que responde
con la forma real de `generate_link` (ver `tests/unit/test_user_invitation_mail.py`
para los fixtures capturados), y el correo lo recibe un `RecordingProvider`.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.core.settings import get_settings
from app.modules.identity import auth_admin
from app.modules.notifications import dispatcher, providers
from app.modules.notifications.providers import RecordingProvider, SendResult

FRONT = "https://app.test"
FROM = '"Prendo" <notificaciones@prendo.com.co>'


async def _postgres_available() -> bool:
    try:
        async with engine.connect():
            return True
    except Exception:
        return False


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _require_postgres() -> None:
    if not await _postgres_available():
        pytest.skip("Postgres local no disponible: correr `supabase start` primero.")


async def _rows(sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    async with AsyncSessionLocal() as s:
        return list((await s.execute(text(sql), params or {})).all())


async def _exec(sql: str, params: dict[str, Any] | None = None) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(text(sql), params or {})


@dataclass
class FakeAuth:
    """Supabase Auth de mentira, con el comportamiento REAL verificado contra
    GoTrue v2.195.0 el 24/09/2026: `generate_link` para un correo ya invitado
    devuelve el MISMO id con un token nuevo (y el viejo queda muerto)."""

    calls: list[tuple[str, str, bool | None]] = field(default_factory=list)
    ids: dict[str, UUID] = field(default_factory=dict)
    n: int = 0
    account_exists: bool = True
    regen_error: Exception | None = None

    async def invite_user(
        self, email: str, full_name: str, *, send_email: bool = True
    ) -> auth_admin.Invitation:
        self.calls.append(("invite", email, send_email))
        if self.regen_error is not None and email in self.ids:
            raise self.regen_error
        user_id = self.ids.setdefault(email, uuid4())
        self.n += 1
        if send_email:
            return auth_admin.Invitation(user_id=user_id, link=None)
        hashed = f"hash{self.n:04d}"
        return auth_admin.Invitation(
            user_id=user_id,
            link=f"{FRONT}/auth/callback?token_hash={hashed}&type=invite",
            hashed_token=hashed,
            invited_at=f"2026-09-25T00:14:{self.n:02d}.223595209Z",
        )

    async def auth_user_exists(self, user_id: UUID | str) -> bool:
        self.calls.append(("exists", str(user_id), None))
        return self.account_exists

    def generate_link_calls(self) -> int:
        return sum(1 for c in self.calls if c[0] == "invite" and c[2] is False)


@pytest.fixture
def fake_auth(monkeypatch: pytest.MonkeyPatch) -> FakeAuth:
    fake = FakeAuth()
    monkeypatch.setattr(auth_admin, "invite_user", fake.invite_user)
    monkeypatch.setattr(auth_admin, "auth_user_exists", fake.auth_user_exists)
    return fake


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> RecordingProvider:
    """Proveedor configurado: el que ve tanto el request como el job."""
    recording = RecordingProvider()
    monkeypatch.setattr(providers, "get_default_provider", lambda: recording)
    return recording


@pytest.fixture(autouse=True)
def frontend_url(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("FRONTEND_URL", FRONT)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _cleanup(company_id: UUID) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        for sql in (
            "delete from public.notification_delivery where company_id = :id",
            "delete from public.notification_event where company_id = :id",
            "delete from public.subscription_event where company_id = :id",
            "delete from public.app_user where company_id = :id",
            "delete from public.role_permission where role_id in "
            "(select id from public.role where company_id = :id)",
            "delete from public.role where company_id = :id",
            "delete from public.account where company_id = :id",
            "delete from public.cash_register where company_id = :id",
            "delete from public.subscription where company_id = :id",
            "delete from public.company where id = :id",
        ):
            await s.execute(text(sql), {"id": str(company_id)})


@pytest_asyncio.fixture
async def company(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict[str, Any], None]:
    """Empresa con un Admin y un rol Bodega. Los avisos de la empresa quedan
    como nacen en producción: APAGADOS."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    cid, admin_role, bodega_role, admin_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text("insert into public.company (id, name) values (:id, 'Compraventa Invita')"),
            {"id": str(cid)},
        )
        await s.execute(
            text(
                "insert into public.role (id, company_id, name, is_seed) values "
                "(:a, :cid, 'Admin', true), (:b, :cid, 'Bodega', true)"
            ),
            {"a": str(admin_role), "b": str(bodega_role), "cid": str(cid)},
        )
        await s.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :r, id from public.permission"
            ),
            {"r": str(admin_role)},
        )
        await s.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :r, 'Dueña', :email, 'active')"
            ),
            {
                "id": str(admin_id),
                "cid": str(cid),
                "r": str(admin_role),
                "email": f"{admin_id}@x.co",
            },
        )
        plan_id = (await s.execute(text("select id from public.plan limit 1"))).scalar_one()
        await s.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :p, 'active', current_date + 30)"
            ),
            {"cid": str(cid), "p": str(plan_id)},
        )
    token = make_token(private_pem, sub=str(admin_id), company_id=str(cid), role_id=str(admin_role))
    yield {"id": cid, "bodega_role": bodega_role, "token": token}
    await _cleanup(cid)


def _invite(client: TestClient, company: dict[str, Any], **extra: Any) -> Any:
    return client.post(
        "/api/v1/identity/invitations",
        headers={"Authorization": f"Bearer {company['token']}"},
        json={
            "email": "ana@example.com",
            "full_name": "Ana María Gómez",
            "role_id": str(company["bodega_role"]),
            **extra,
        },
    )


async def _deliveries(company_id: UUID) -> list[Any]:
    return await _rows(
        """
        select d.id, d.status, d.attempts, d.to_address, d.recipient_user_id, d.last_error,
               d.scheduled_at, e.event_type, e.audience, e.dedupe_key, e.payload::text as payload,
               e.entity_type, e.entity_id
        from public.notification_delivery d
        join public.notification_event e on e.id = d.event_id
        where d.company_id = :cid order by d.created_at
        """,
        {"cid": str(company_id)},
    )


async def _audit_after(company_id: UUID) -> dict[str, Any]:
    rows = await _rows(
        "select after from public.audit_log where company_id = :cid and action = 'invite_user'",
        {"cid": str(company_id)},
    )
    assert len(rows) == 1
    after: dict[str, Any] = rows[0][0]
    return after


# ------------------------------------------------------------ camino feliz ----


@pytest.mark.asyncio
async def test_invitation_goes_out_through_our_mail_right_after_commit(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """El caso que se rompía con `INVITE_RATE_LIMITED`: ahora Supabase solo
    emite el enlace (sin correo) y el correo sale por Resend.

    Y sale en el MISMO request, no a la noche: el `BackgroundTasks` corre
    después de la respuesta. **Esto falla si el envío corre antes del commit**
    — que es lo que pasa por defecto en FastAPI 0.141, porque la dependencia
    `get_db` cierra su transacción DESPUÉS de las tareas de fondo: el
    despachador, en otra conexión, no ve la fila todavía."""
    response = _invite(client, company)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invite_delivery"] == "email"
    # El enlace es una credencial: si salió por correo no viaja también en la respuesta.
    assert body["invite_link"] is None
    # A Supabase se le pidió el enlace SIN correo.
    assert fake_auth.calls == [("invite", "ana@example.com", False)]

    assert len(outbox.outbox) == 1
    message = outbox.outbox[0]
    link = f"{FRONT}/auth/callback?token_hash=hash0001&type=invite"
    assert message.to == "ana@example.com"
    assert message.from_header == FROM
    assert message.reply_to is None
    assert link in message.text
    assert "/auth/v1/verify" not in message.text + message.html
    assert "Compraventa Invita" in message.subject

    [delivery] = await _deliveries(company["id"])
    m = delivery._mapping
    assert m["status"] == "sent"
    assert m["attempts"] == 1
    assert m["event_type"] == "user_invitation"
    assert m["audience"] == "platform"
    assert str(m["recipient_user_id"]) == body["id"]
    assert (m["entity_type"], str(m["entity_id"])) == ("app_user", body["id"])
    assert message.idempotency_key == f"delivery-{m['id']}"


@pytest.mark.asyncio
async def test_the_token_is_never_stored(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """El token es una credencial que vence en minutos: no va al `payload`,
    ni al `last_error`, ni al `audit_log`. Si hay que reenviar, se pide uno nuevo."""
    assert _invite(client, company).status_code == 201
    [delivery] = await _deliveries(company["id"])
    assert "hash0001" not in str(tuple(delivery))
    assert "hash0001" not in str(await _audit_after(company["id"]))


@pytest.mark.asyncio
async def test_the_company_switch_does_not_block_the_invitation(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """Los avisos de la empresa nacen apagados (§15.2-5). Antes de esta fase,
    `record_event` y el despachador los miraban para TODO evento: la
    invitación habría nacido sin entrega y ninguna empresa podría invitar por
    correo hasta encender los avisos a sus clientes."""
    settings = await _rows(
        "select settings from public.company where id = :id", {"id": str(company["id"])}
    )
    assert not ((settings[0][0] or {}).get("notifications") or {}).get("enabled")
    # Y aunque alguien escribiera el jsonb a mano para apagarla:
    await _exec(
        "update public.company set settings = jsonb_build_object('notifications', "
        "jsonb_build_object('enabled', false, 'events', "
        "jsonb_build_object('user_invitation', false))) where id = :id",
        {"id": str(company["id"])},
    )
    assert _invite(client, company).status_code == 201
    assert len(outbox.outbox) == 1


@pytest.mark.asyncio
async def test_dedupe_key_is_per_user_and_per_invitation(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """`invitation:<usuario>:<invited_at>`. El usuario solo no alcanza: el día
    que exista «reenviar invitación», una segunda invitación a la misma persona
    es un hecho NUEVO (GoTrue le pone otro `invited_at`) y la llave no puede
    tragársela. La misma invitación registrada dos veces sí es una sola."""
    body = _invite(client, company).json()
    [delivery] = await _deliveries(company["id"])
    assert delivery._mapping["dedupe_key"] == (
        f"invitation:{body['id']}:2026-09-25T00:14:01.223595209Z"
    )

    from app.modules.notifications import integration as notifications_integration

    async with AsyncSessionLocal() as s, s.begin():
        again = await notifications_integration.record_user_invitation(
            s,
            company_id=company["id"],
            user_id=UUID(body["id"]),
            email="ana@example.com",
            invited_at="2026-09-25T00:14:01.223595209Z",
        )
    assert again is None
    assert len(await _deliveries(company["id"])) == 1


# ------------------------------------------------------ sin proveedor / URL ----


@pytest.mark.asyncio
async def test_without_provider_supabase_sends_it_as_before(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth
) -> None:
    """Sin `RESEND_API_KEY` (el conftest la vacía → `NullProvider`) la
    invitación NO queda muda: vuelve al correo de Supabase de siempre. Y no se
    registra un evento sin entrega, que en este sistema significa «apagado»."""
    response = _invite(client, company)
    assert response.status_code == 201, response.text
    assert response.json()["invite_delivery"] == "email_supabase"
    assert fake_auth.calls == [("invite", "ana@example.com", True)]
    assert await _deliveries(company["id"]) == []
    events = await _rows(
        "select 1 from public.notification_event where company_id = :id", {"id": str(company["id"])}
    )
    assert events == []
    assert (await _audit_after(company["id"]))["delivery"] == "email_supabase"


@pytest.mark.asyncio
async def test_without_frontend_url_supabase_sends_it_as_before(
    client: TestClient,
    company: dict[str, Any],
    fake_auth: FakeAuth,
    outbox: RecordingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `FRONTEND_URL` no hay enlace seguro que armar, y un `action_link`
    (GET de un solo uso) dentro de un correo lo quema el escáner del buzón."""
    monkeypatch.setenv("FRONTEND_URL", "")
    get_settings.cache_clear()
    response = _invite(client, company)
    assert response.status_code == 201, response.text
    assert response.json()["invite_delivery"] == "email_supabase"
    assert fake_auth.calls == [("invite", "ana@example.com", True)]
    assert outbox.outbox == []


@pytest.mark.asyncio
async def test_link_mode_is_untouched(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """«Generar enlace» (`send_email=false`) sigue igual: el enlace vuelve en
    la respuesta, no sale correo y no hay evento que notificar."""
    response = _invite(client, company, send_email=False)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invite_delivery"] == "link"
    assert body["invite_link"] == f"{FRONT}/auth/callback?token_hash=hash0001&type=invite"
    assert outbox.outbox == []
    assert await _deliveries(company["id"]) == []
    assert (await _audit_after(company["id"]))["delivery"] == "link"


# --------------------------------------------------------- el job como red ----


async def _invite_with_failed_send(
    client: TestClient, company: dict[str, Any], outbox: RecordingProvider
) -> Any:
    outbox.fail_with = SendResult(ok=False, retryable=True, error="HTTP 503: caído")
    response = _invite(client, company)
    assert response.status_code == 201, response.text
    outbox.fail_with = None
    [delivery] = await _deliveries(company["id"])
    assert delivery._mapping["status"] == "failed"
    assert delivery._mapping["attempts"] == 1
    return response.json()


async def _run_job(company_id: UUID) -> dispatcher.DispatchStats:
    return await dispatcher.dispatch_due(
        provider=providers.get_default_provider(),
        now=datetime.now(UTC) + timedelta(hours=2),
        only_company_ids=[company_id],
    )


@pytest.mark.asyncio
async def test_a_failed_send_is_retried_by_the_job_with_a_fresh_link(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """Resend caído en el momento de invitar: la entrega queda `failed` y el
    job la retoma. El token del primer intento no se guardó —y aunque se
    hubiera guardado, a las horas ya estaría vencido—, así que el job le pide
    a Supabase uno NUEVO para la misma cuenta.

    La llave de idempotencia de Resend cambia por intento: el cuerpo lleva otro
    token, y Resend responde 409 `invalid_idempotent_request` si se reusa una
    llave con otro payload (documentado en resend.com/docs, «Idempotency keys»)."""
    await _invite_with_failed_send(client, company, outbox)

    stats = await _run_job(company["id"])

    assert stats.by_status == {"sent": 1}
    assert fake_auth.generate_link_calls() == 2
    [message] = outbox.outbox
    assert f"{FRONT}/auth/callback?token_hash=hash0002&type=invite" in message.text
    assert "hash0001" not in message.text
    [delivery] = await _deliveries(company["id"])
    assert delivery._mapping["status"] == "sent"
    assert delivery._mapping["attempts"] == 2
    assert message.idempotency_key == f"delivery-{delivery._mapping['id']}-a2"


@pytest.mark.asyncio
async def test_job_does_not_invite_someone_who_already_got_in(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """Mientras el correo esperaba, el admin usó «Generar enlace» y la persona
    entró. Mandarle ahora una invitación es ruido, y pedir un enlace nuevo
    sería tocar su cuenta sin motivo: ni siquiera se llama a Supabase."""
    body = await _invite_with_failed_send(client, company, outbox)
    await _exec("update public.app_user set status = 'active' where id = :id", {"id": body["id"]})
    calls_before = len(fake_auth.calls)

    stats = await _run_job(company["id"])

    assert stats.by_status == {"suppressed": 1}
    assert len(fake_auth.calls) == calls_before
    assert outbox.outbox == []


@pytest.mark.asyncio
async def test_job_stops_if_supabase_says_the_account_is_already_active(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """La persona puso su contraseña pero todavía no hizo ningún request al
    backend (`app_user` sigue `invited`). GoTrue responde 422 `email_exists`
    — respuesta real capturada — y eso NO es una falla: es que ya no hace falta."""
    await _invite_with_failed_send(client, company, outbox)
    fake_auth.regen_error = auth_admin.EmailAlreadyRegisteredError("ya existe")

    stats = await _run_job(company["id"])

    assert stats.by_status == {"suppressed": 1}
    [delivery] = await _deliveries(company["id"])
    assert "ya activó" in delivery._mapping["last_error"]
    assert outbox.outbox == []


@pytest.mark.asyncio
async def test_job_does_not_create_an_orphan_account(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """Si alguien borró la cuenta desde el panel de Supabase, `generate_link`
    con `type=invite` NO falla: crea una cuenta nueva, con otro id, que no
    corresponde a ningún `app_user`. Por eso antes se pregunta si existe."""
    await _invite_with_failed_send(client, company, outbox)
    fake_auth.account_exists = False
    links_before = fake_auth.generate_link_calls()

    stats = await _run_job(company["id"])

    assert stats.by_status == {"dead": 1}
    assert fake_auth.generate_link_calls() == links_before
    [delivery] = await _deliveries(company["id"])
    assert "ya no existe" in delivery._mapping["last_error"]


@pytest.mark.asyncio
async def test_supabase_rate_limit_while_regenerating_is_retried(
    client: TestClient, company: dict[str, Any], fake_auth: FakeAuth, outbox: RecordingProvider
) -> None:
    """Un 429 de Supabase al pedir el enlace es «espera», igual que un 429 de
    Resend: mismo backoff, mismo contador de intentos."""
    await _invite_with_failed_send(client, company, outbox)
    fake_auth.regen_error = auth_admin.InviteRateLimitedError("espera")

    stats = await _run_job(company["id"])

    assert stats.by_status == {"failed": 1}
    [delivery] = await _deliveries(company["id"])
    assert delivery._mapping["attempts"] == 2
    assert "INVITE_RATE_LIMITED" in delivery._mapping["last_error"]


# ------------------------------------------------------------ alta de empresa ----


@pytest.mark.asyncio
async def test_new_company_first_admin_by_mail_uses_our_mail_too(
    client: TestClient,
    fake_auth: FakeAuth,
    outbox: RecordingProvider,
    monkeypatch: pytest.MonkeyPatch,
    rsa_keypair: tuple[str, object],
) -> None:
    """El alta de empresa con `send_email=true` pasa por la misma función de
    integración, así que hereda el cambio — y es el camino que más dependía
    del correo de Supabase."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    token = make_token(private_pem, sub=str(uuid4()), app_metadata={"platform_role": "super_admin"})
    response = client.post(
        "/api/v1/platform/companies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Empresa Nueva Correo",
            "plan_code": "full",
            "subscription_expires_at": "2099-01-01",
            "first_admin_email": "duena-nueva@example.com",
            "first_admin_full_name": "Dueña Nueva",
            "send_email": True,
        },
    )
    assert response.status_code == 201, response.text
    company_id = UUID(response.json()["id"])
    try:
        assert response.json()["admin_invite_link"] is None
        [message] = outbox.outbox
        assert message.to == "duena-nueva@example.com"
        assert "Empresa Nueva Correo" in message.subject
        [delivery] = await _deliveries(company_id)
        assert delivery._mapping["status"] == "sent"
    finally:
        await _cleanup(company_id)
