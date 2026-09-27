"""Peticiones SIMULTÁNEAS de verdad contra la app, para probar carreras.

`TestClient` es síncrono: dos `client.post` seguidos nunca se pisan, así que
un test escrito con él pasa aunque el servicio lea → valide → escriba sin
bloquear nada. Así sobrevivieron F4-01/F4-02 (abonos y recargos dobles),
F5-01 (saldo gastado N veces) y F6-01 (factura pagada dos veces) de la
auditoría del 27/09/2026: la suite no tenía cómo dispararlas.

Acá cada petición corre como una tarea de `asyncio.gather` sobre la app ASGI
y abre su propia sesión (el engine es `NullPool`: una conexión por request),
así que se entrelazan en cada `await` a la base — las dos leen el mismo
estado antes de que cualquiera escriba, que es exactamente la carrera del
mostrador cuando dos cajeros (o un doble clic) atacan el mismo documento.

`raise_app_exceptions=False`: un 500 debe llegar al test como respuesta, para
que la aserción diga "esperaba un `code` de negocio y llegó un 500" en vez de
reventar con la traza de la excepción.
"""

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx

from app.main import app


class Peticion:
    def __init__(
        self,
        method: str,
        url: str,
        *,
        token: str,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> None:
        self.method = method
        self.url = url
        self.json = json
        self.headers = {"Authorization": f"Bearer {token}"}
        if idempotency_key:
            self.headers["Idempotency-Key"] = idempotency_key


async def en_paralelo(peticiones: Sequence[Peticion]) -> list[httpx.Response]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return list(
            await asyncio.gather(
                *(c.request(p.method, p.url, headers=p.headers, json=p.json) for p in peticiones)
            )
        )
