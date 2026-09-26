"""Límite de tasa en memoria, por proceso (docs/NOTIFICACIONES.md §17-bis).

Hoy lo usa un solo lugar: el endpoint PÚBLICO de baja
(`/api/v1/public/unsubscribe/{token}`), el único de la API que responde sin
sesión. Todo lo demás pasa por un JWT de Supabase, y un JWT ya es un límite.

**Por qué en memoria y no compartido.** Un contador compartido entre máquinas
pide un lugar compartido: una tabla (y este cambio no puede traer migración) o
un Redis (infraestructura nueva para cuidar un endpoint que recibe, con suerte,
unas decenas de visitas al día). Y el objetivo no lo necesita: el token es un
HMAC de 128 bits, así que acá no hay fuerza bruta que frenar — lo que se corta
es el abuso (un script golpeando la misma URL, o una IP barriendo tokens
basura), y para eso basta con que cada máquina se defienda sola.

**Lo que eso cuesta, dicho claro:**

- **El límite es POR MÁQUINA.** Con N máquinas de Fly detrás del proxy, quien
  reparte sus pedidos entre todas llega a N veces el límite. Hoy dev corre una
  (y se apaga sola) y prod una siempre encendida; cada máquina corre UN worker
  de uvicorn (`Dockerfile`), así que proceso = máquina.
- **Se olvida al reiniciar.** Un deploy o un arranque en frío empieza de cero.
- **Ventana fija, no deslizante.** En el borde de dos ventanas caben hasta
  2× el límite en poco tiempo. Para cortar abuso da igual; para cobrar por
  uso no serviría.

Si algún día hace falta un límite GLOBAL (un endpoint público caro, un
login propio), esto no es la base: es la tabla o el Redis.

Sin `await` adentro de `hit`: en el loop de asyncio de un worker cada llamada
es atómica, sin candados.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from fastapi import Request, status

from app.core.errors import AppError

#: Todas las instancias, para que los tests las vacíen entre caso y caso: el
#: estado es global al proceso, y la suite entera corre en uno solo.
_ALL: list[FixedWindowLimiter] = []


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message, details={"retry_after_seconds": retry_after_seconds})
        # RFC 9110 §10.2.3: el cliente (o el proxy de un proveedor de correo)
        # sabe cuándo volver sin tener que leer el cuerpo.
        self.headers = {"Retry-After": str(retry_after_seconds)}


class FixedWindowLimiter:
    """`limit` pedidos por `window_seconds`, por llave, en ventanas fijas.

    `max_keys` acota la memoria: una IP que manda tokens distintos en cada
    pedido crearía una llave por pedido. Al llegar al tope se barren las
    ventanas vencidas; si aun así no cabe, se vacía todo — perder el conteo de
    un minuto es mejor que dejar que un atacante haga crecer el proceso hasta
    que Fly lo mate por memoria.
    """

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._hits: dict[str, tuple[float, int]] = {}
        _ALL.append(self)

    def hit(self, key: str) -> int | None:
        """Cuenta un pedido. `None` si pasa; si no, los segundos que faltan.

        Un pedido rechazado NO cuenta: quien insiste bloqueado no alarga su
        propio castigo, solo espera a que termine la ventana."""
        now = self._clock()
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self.window_seconds:
            start, count = now, 0
        if count >= self.limit:
            return max(1, math.ceil(start + self.window_seconds - now))
        if key not in self._hits and len(self._hits) >= self._max_keys:
            self._prune(now)
        self._hits[key] = (start, count + 1)
        return None

    def _prune(self, now: float) -> None:
        vencidas = [k for k, (s, _) in self._hits.items() if now - s >= self.window_seconds]
        for k in vencidas:
            del self._hits[k]
        if len(self._hits) >= self._max_keys:
            self._hits.clear()

    def reset(self) -> None:
        self._hits.clear()


def reset_all() -> None:
    """Solo para tests."""
    for limiter in _ALL:
        limiter.reset()


def client_ip(request: Request) -> str:
    """La IP de quien pide, detrás del proxy de Fly.

    `request.client.host` es el proxy, no la persona: Fly deja la IP real en
    `Fly-Client-IP`. Sin esa cabecera (local, tests) se usa la del socket."""
    forwarded = request.headers.get("fly-client-ip", "").strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "desconocida"
