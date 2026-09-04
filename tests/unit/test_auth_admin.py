"""El payload de la invitación a Supabase Auth.

Existe por DOS bugs reales, y el segundo se escondió detrás del primero.

1. `invite_user` no mandaba `redirect_to`, así que Supabase caía en su "Site
   URL" y el link del correo moría en "This site can't be reached".

2. Se agregó `redirect_to`… en el BODY. `/admin/generate_link` lo lee de ahí
   —por eso "Generar enlace" funcionaba y todo parecía arreglado— pero
   `/invite` lo lee SOLO del query string. En el body lo ignora en silencio y
   vuelve a caer en el Site URL, que es la raíz de la app: el invitado entra
   directo, con sesión, sin que le pidan contraseña. Y como queda sin
   contraseña, tampoco puede volver a entrar después.

   Crear una empresa siempre manda correo, así que ese camino estaba roto al
   100% mientras el de invitar a un usuario se veía perfecto.

Los tests de integración mockean `invite_user` ENTERO, así que ninguno mira
lo que se manda — por eso esto es unitario. Y el fake client de acá no
capturaba `params`, así que tampoco podía ver el bug 2: mirar solo el body
era mirar donde el dato no estaba.
"""

from typing import Any
from uuid import uuid4

import pytest

from app.core.settings import get_settings
from app.modules.identity import auth_admin


class _FakeResponse:
    status_code = 200

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id
        self.text = ""

    def json(self) -> dict[str, Any]:
        return {"id": self._user_id}


class _FakeClient:
    """Captura el payload en vez de salir a la red."""

    captured: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(
        self, url: str, headers: dict, json: dict, params: dict | None = None
    ) -> _FakeResponse:
        # `params` se captura desde que se descubrió que `/invite` lee
        # `redirect_to` SOLO del query string: antes esta firma no lo recibía
        # siquiera, y por eso los tests de este archivo —escritos justo para
        # el bug de "falta redirect_to"— no vieron la segunda mitad del
        # problema. Mirar solo el body era mirar donde no estaba.
        _FakeClient.captured = {
            "url": url,
            "headers": headers,
            "json": json,
            "params": params or {},
        }
        return _FakeResponse(str(uuid4()))


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Any:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invite_includes_redirect_to_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("nuevo@example.com", "Nuevo Usuario")

    payload = _FakeClient.captured["json"]
    assert payload["redirect_to"] == "https://app.example.com/auth/callback"
    assert payload["email"] == "nuevo@example.com"
    assert payload["data"] == {"full_name": "Nuevo Usuario"}


@pytest.mark.asyncio
async def test_invite_normalizes_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una URL con `/` final produciría `//auth/callback`, que Supabase no
    matchearía contra su lista de Redirect URLs permitidas — y volvería a caer
    en la Site URL, o sea el mismo bug con otra causa."""
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com/")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("otro@example.com", "Otro")

    assert _FakeClient.captured["json"]["redirect_to"] == "https://app.example.com/auth/callback"


@pytest.mark.asyncio
async def test_invite_omits_redirect_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `FRONTEND_URL` no se manda un `redirect_to` vacío (Supabase lo
    rechazaría): se omite y queda el comportamiento anterior."""
    monkeypatch.setenv("FRONTEND_URL", "")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("sin@example.com", "Sin Redirect")

    assert "redirect_to" not in _FakeClient.captured["json"]


class _RateLimitedResponse:
    status_code = 429
    text = '{"error_code":"over_email_send_rate_limit"}'

    def json(self) -> dict[str, Any]:
        return {}


class _RateLimitedClient(_FakeClient):
    async def post(self, *args: Any, **kwargs: Any) -> Any:
        return _RateLimitedResponse()


@pytest.mark.asyncio
async def test_rate_limit_no_se_reporta_como_falla_del_sistema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un 429 de Supabase significa "espera", no "algo se rompió".

    Antes caía en `AuthAdminError` (502, "No se pudo invitar al usuario en
    Supabase Auth"), que manda al admin a buscar un problema inexistente: el
    servicio de correo incluido de Supabase tiene un límite bajo a propósito
    porque está pensado para pruebas. Se distingue para poder decirle qué
    hacer — esperar — en vez de dejarlo adivinando.
    """
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _RateLimitedClient)

    with pytest.raises(auth_admin.InviteRateLimitedError) as exc:
        await auth_admin.invite_user("nuevo@example.com", "Nuevo Usuario")

    assert exc.value.status_code == 429
    assert exc.value.code == "INVITE_RATE_LIMITED"
    assert "espera" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_invite_sends_redirect_in_the_query_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/invite` lee `redirect_to` SOLO del query string.

    Es la mitad del bug que se escondió durante semanas: en el body funciona
    para `generate_link` y no para `invite`, así que "Generar enlace" andaba
    bien y el correo de alta de empresa mandaba al invitado directo a la app,
    sin contraseña.
    """
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("empresa@example.com", "Admin Nuevo", send_email=True)

    captured = _FakeClient.captured
    assert captured["url"].endswith("/auth/v1/invite")
    assert captured["params"]["redirect_to"] == "https://app.example.com/auth/callback"


@pytest.mark.asyncio
async def test_generate_link_also_sends_it_in_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """El otro camino usa el MISMO mecanismo.

    El cliente oficial de Supabase pone `redirect_to` en el query para los dos
    endpoints; se replica para no tener dos comportamientos que mantener. El
    body se conserva además porque es lo que `generate_link` ya venía
    aceptando — un campo de más que el servidor ignora no cuesta nada, y
    quitarlo arriesgaría el único camino que hoy sí funciona.
    """
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("link@example.com", "Por Enlace", send_email=False)

    captured = _FakeClient.captured
    assert captured["url"].endswith("/auth/v1/admin/generate_link")
    assert captured["params"]["redirect_to"] == "https://app.example.com/auth/callback"
    assert captured["json"]["redirect_to"] == "https://app.example.com/auth/callback"
    assert captured["json"]["type"] == "invite"


@pytest.mark.asyncio
async def test_no_frontend_url_sends_no_redirect_anywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin `FRONTEND_URL` no se inventa un destino.

    Mandar un `redirect_to` vacío o basura sería peor que no mandarlo: Supabase
    lo rechazaría o caería en la Site URL igual, pero con un error más difícil
    de leer.
    """
    monkeypatch.setenv("FRONTEND_URL", "")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("sin@example.com", "Sin URL")

    assert _FakeClient.captured["params"] == {}
    assert "redirect_to" not in _FakeClient.captured["json"]


class _FakeLinkResponse(_FakeResponse):
    """Lo que devuelve `/admin/generate_link` de verdad: trae `hashed_token`."""

    def json(self) -> dict[str, Any]:
        return {
            "id": self._user_id,
            "action_link": "https://proyecto.supabase.co/auth/v1/verify?token=abc&type=invite",
            "hashed_token": "abc123hash",
        }


class _FakeLinkClient(_FakeClient):
    async def post(
        self, url: str, headers: dict, json: dict, params: dict | None = None
    ) -> _FakeResponse:
        await super().post(url, headers=headers, json=json, params=params)
        return _FakeLinkResponse(str(uuid4()))


@pytest.mark.asyncio
async def test_invite_link_points_to_the_app_not_to_gotrue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El enlace entregado NO puede ser el `action_link` de GoTrue.

    `action_link` es un GET de un solo uso: cualquier crawler de vista previa
    (WhatsApp, Telegram, Gmail) lo quema con solo pedir la URL, y la persona
    llega a un enlace muerto. Reproducido contra el proyecto dev el
    03/09/2026 — ver `auth_admin._app_link`.

    El `token_hash` en cambio se canjea por POST, así que un GET del crawler
    solo se baja el HTML de la SPA.
    """
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeLinkClient)

    invitacion = await auth_admin.invite_user("nuevo@example.com", "Nuevo", send_email=False)

    assert (
        invitacion.link == "https://app.example.com/auth/callback?token_hash=abc123hash&type=invite"
    )
    assert "/auth/v1/verify" not in (invitacion.link or "")


@pytest.mark.asyncio
async def test_recovery_link_points_to_the_app_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recuperar contraseña usa el mismo endpoint, así que hereda el mismo bug."""
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeLinkClient)

    link = await auth_admin.generate_recovery_link("olvidadizo@example.com")

    assert link == "https://app.example.com/auth/callback?token_hash=abc123hash&type=recovery"


@pytest.mark.asyncio
async def test_without_frontend_url_falls_back_to_the_gotrue_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `FRONTEND_URL` no hay a dónde apuntar, y un enlace frágil es mejor
    que ninguno: la alternativa sería dejar al admin sin forma de dar de alta
    a nadie."""
    monkeypatch.setenv("FRONTEND_URL", "")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeLinkClient)

    invitacion = await auth_admin.invite_user("sin@example.com", "Sin URL", send_email=False)

    assert invitacion.link == "https://proyecto.supabase.co/auth/v1/verify?token=abc&type=invite"
