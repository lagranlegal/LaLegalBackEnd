"""La invitación de usuario (P1) por nuestro correo — la parte pura
(docs/NOTIFICACIONES.md §16).

Tres cosas se prueban acá sin BD:

1. Lo que `auth_admin` saca de la respuesta de GoTrue: el `hashed_token` y el
   `invited_at`, y si la cuenta de acceso todavía existe.
2. La plantilla: remitente de plataforma, el enlace de la app, y el candado de
   que el correo NUNCA lleve un token canjeable por GET.
3. Que el interruptor de la empresa no apague la invitación.

**Los fixtures de GoTrue son respuestas REALES**, capturadas el 24/09/2026
contra el GoTrue local de `supabase start` (v2.195.0): `POST
/auth/v1/admin/generate_link` con `type=invite` y `GET
/auth/v1/admin/users/{id}`. Se cambiaron solo los valores (correo, ids,
tokens); la FORMA es la que devolvió el servidor. Un fixture escrito de
memoria confirma el bug en vez de encontrarlo.
"""

from typing import Any

import httpx
import pytest

from app.core.settings import get_settings
from app.modules.identity import auth_admin
from app.modules.notifications import catalog, preferences, templates

USER_ID = "717ab9d7-3e9f-4a10-8b81-1a4f42c8293b"

#: `POST /auth/v1/admin/generate_link` {"type": "invite", ...} → 200. Real.
GENERATE_LINK_INVITE_200: dict[str, Any] = {
    "id": USER_ID,
    "aud": "authenticated",
    "role": "authenticated",
    "email": "invitada@example.com",
    "invited_at": "2026-09-25T00:14:39.223595209Z",
    "phone": "",
    "confirmation_sent_at": "2026-09-25T00:14:39.223595209Z",
    "app_metadata": {"provider": "email", "providers": ["email"]},
    "user_metadata": {"full_name": "Invitada Prueba"},
    "identities": [
        {
            "identity_id": "b776304d-a6a8-4d62-8916-425a307c7a93",
            "id": USER_ID,
            "user_id": USER_ID,
            "identity_data": {
                "email": "invitada@example.com",
                "email_verified": False,
                "phone_verified": False,
                "sub": USER_ID,
            },
            "provider": "email",
            "last_sign_in_at": "2026-09-25T00:14:39.2343695Z",
            "created_at": "2026-09-25T00:14:39.234701Z",
            "updated_at": "2026-09-25T00:14:39.234701Z",
            "email": "invitada@example.com",
        }
    ],
    "created_at": "2026-09-25T00:14:39.228003Z",
    "updated_at": "2026-09-25T00:14:39.236774Z",
    "is_anonymous": False,
    "action_link": (
        "http://127.0.0.1:54321/auth/v1/verify?token=hashdeprueba0001"
        "&type=invite&redirect_to=http://127.0.0.1:3000"
    ),
    "email_otp": "709414",
    "hashed_token": "hashdeprueba0001",
    "verification_type": "invite",
    "redirect_to": "http://127.0.0.1:3000",
}

#: `GET /auth/v1/admin/users/{id}` de un id que no existe → 404. Real.
GET_USER_404 = {"code": 404, "error_code": "user_not_found", "msg": "User not found"}

#: `POST /auth/v1/admin/generate_link` {"type": "invite"} para alguien que YA
#: activó su cuenta → 422. Real. Es lo que ve el job si la persona entró por
#: otro camino (p. ej. «Generar enlace») antes de que saliera el correo.
GENERATE_LINK_EMAIL_EXISTS_422 = {
    "code": 422,
    "error_code": "email_exists",
    "msg": "A user with this email address has already been registered",
}


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mock_http(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        response: httpx.Response = handler(request)
        return response

    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _client)
    return seen


# ------------------------------------------------------------ auth_admin ----


@pytest.mark.asyncio
async def test_generate_link_exposes_the_hashed_token_and_invited_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El correo necesita el `hashed_token` suelto (no un enlace ya armado que
    podría ser el `action_link`), y la llave del evento necesita `invited_at`."""
    _mock_http(monkeypatch, lambda _r: httpx.Response(200, json=GENERATE_LINK_INVITE_200))

    invitation = await auth_admin.invite_user("invitada@example.com", "Invitada", send_email=False)

    assert str(invitation.user_id) == USER_ID
    assert invitation.hashed_token == "hashdeprueba0001"
    assert invitation.invited_at == "2026-09-25T00:14:39.223595209Z"


def test_invitation_email_link_has_the_same_form_as_generar_enlace() -> None:
    """La MISMA forma que ya entrega «Generar enlace» (`_app_link`): el front
    la canjea por POST y no hay que tocarlo."""
    link = auth_admin.invitation_email_link("hashdeprueba0001")
    assert link == "https://app.example.com/auth/callback?token_hash=hashdeprueba0001&type=invite"


def test_invitation_email_link_without_frontend_url_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `FRONTEND_URL` NO se cae al `action_link` (como sí hace «Generar
    enlace»): en un correo, un GET de un solo uso no es "frágil pero mejor que
    nada" — lo quema el escáner del buzón antes que la persona."""
    monkeypatch.setenv("FRONTEND_URL", "")
    get_settings.cache_clear()
    assert auth_admin.invitation_email_link("hashdeprueba0001") is None


@pytest.mark.asyncio
async def test_auth_user_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(USER_ID):
            return httpx.Response(200, json={**GENERATE_LINK_INVITE_200})
        return httpx.Response(404, json=GET_USER_404)

    seen = _mock_http(monkeypatch, handler)

    assert await auth_admin.auth_user_exists(USER_ID) is True
    assert await auth_admin.auth_user_exists("00000000-0000-4000-8000-000000000000") is False
    assert seen[0].method == "GET"
    assert seen[0].url.path == f"/auth/v1/admin/users/{USER_ID}"


@pytest.mark.asyncio
async def test_auth_user_exists_does_not_hide_a_broken_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un 500 no es "la cuenta no existe": confundirlos mandaría la invitación a
    `dead` por un Supabase caído, cuando lo correcto es reintentar."""
    _mock_http(monkeypatch, lambda _r: httpx.Response(500, text="boom"))
    with pytest.raises(auth_admin.AuthAdminError) as exc:
        await auth_admin.auth_user_exists(USER_ID)
    assert exc.value.code == "AUTH_ADMIN_ERROR"


@pytest.mark.asyncio
async def test_reinvite_after_activation_is_email_already_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_http(monkeypatch, lambda _r: httpx.Response(422, json=GENERATE_LINK_EMAIL_EXISTS_422))
    with pytest.raises(auth_admin.EmailAlreadyRegisteredError) as exc:
        await auth_admin.invite_user("invitada@example.com", "Invitada", send_email=False)
    assert exc.value.code == "EMAIL_ALREADY_REGISTERED"


# --------------------------------------------------------------- plantilla ----

BRAND = templates.Branding(
    company_name="LA GRAN LEGAL",
    contact_email="contacto@lagranlegal.example",
    contact_phone="300 000 0000",
    footer_note="Gracias por preferirnos",
)
LINK = "https://app.example.com/auth/callback?token_hash=hashdeprueba0001&type=invite"


def _render(**payload: Any) -> templates.RenderedEmail:
    base = {"invitee_name": "Ana María Gómez", "invite_link": LINK}
    return templates.render("user_invitation", {**base, **payload}, BRAND)


def test_invitation_comes_from_prendo_not_from_the_company() -> None:
    """§8: la contraparte de un usuario de Prendo es Prendo. Sin `(vía …)` y
    sin `Reply-To` de la empresa: responderle a una invitación no es escribirle
    a la compraventa."""
    rendered = _render()
    assert rendered.from_name == "Prendo"
    assert rendered.reply_to is None
    assert "LA GRAN LEGAL" in rendered.subject


def test_invitation_carries_the_app_link_in_text_and_html() -> None:
    rendered = _render()
    assert LINK in rendered.text
    # En el HTML el `&` va escapado dentro del atributo — y sigue siendo el
    # mismo enlace para el navegador.
    assert LINK.replace("&", "&amp;") in rendered.html
    assert "Hola, Ana:" in rendered.text
    assert "LA GRAN LEGAL" in rendered.text


def test_invitation_never_carries_a_get_redeemable_token() -> None:
    """El candado del 03/09/2026 en el último punto posible: aunque un
    productor pasara el `action_link` de GoTrue, la plantilla no lo redacta."""
    # Primero el caso bueno: si la plantilla no existiera, los `raises` de
    # abajo pasarían por la razón equivocada ("sin plantilla").
    assert LINK in _render().text
    action_link = GENERATE_LINK_INVITE_200["action_link"]
    with pytest.raises(ValueError):
        _render(invite_link=action_link)
    with pytest.raises(ValueError):
        _render(invite_link="https://app.example.com/auth/callback#access_token=xyz")


def test_invitation_without_link_is_not_rendered() -> None:
    """Un correo de invitación sin enlace es un correo inútil: mejor `dead`
    (y visible) que un correo que dice «abra este enlace» sin enlace."""
    assert _render().subject
    with pytest.raises(KeyError):
        templates.render("user_invitation", {"invitee_name": "Ana"}, BRAND)


def test_invitation_body_only_names_company_and_invitee() -> None:
    """§9.1 aplicado a la plataforma: nada del payload que no sea el nombre."""
    rendered = _render(role_name="Admin", inviter_email="jefe@example.com", doc_number="1032")
    for body in (rendered.html, rendered.text, rendered.subject):
        assert "jefe@example.com" not in body
        assert "1032" not in body
        # Ni el teléfono ni el `footer_note` del inquilino: el correo es de Prendo.
        assert "300 000 0000" not in body
        assert "Gracias por preferirnos" not in body


def test_invitation_company_name_is_escaped() -> None:
    brand = templates.Branding(company_name="<script>x</script> & Cía")
    rendered = templates.render(
        "user_invitation", {"invitee_name": "Ana", "invite_link": LINK}, brand
    )
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


# ------------------------------------------------------------ preferencias ----


def test_company_switch_does_not_mute_the_invitation() -> None:
    """El interruptor general nace APAGADO (§15.2-5). Si gobernara también la
    invitación, ninguna empresa podría invitar a nadie por correo hasta
    encender los avisos a sus clientes — dos decisiones sin relación."""
    prefs = preferences.parse({})
    assert prefs.enabled is False
    assert prefs.event_enabled("user_invitation") is True


def test_a_stray_override_cannot_mute_the_invitation() -> None:
    """El PATCH ya rechaza `user_invitation` (`NOTIFICATION_EVENT_NOT_CONFIGURABLE`),
    pero el jsonb se puede escribir por otros caminos. Leer tiene que ser tan
    estricto como escribir."""
    prefs = preferences.parse({"notifications": {"events": {"user_invitation": False}}})
    assert prefs.event_enabled("user_invitation") is True
    assert prefs.event_setting("user_invitation") is True


def test_platform_events_are_the_only_ones_that_ignore_the_switch() -> None:
    prefs = preferences.parse({})
    for code, et in catalog.EVENT_TYPES.items():
        if et.audience != "platform":
            assert prefs.event_enabled(code) is False, code
