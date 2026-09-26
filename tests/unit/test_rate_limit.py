"""El limitador en memoria del endpoint público de baja (NOTIFICACIONES §17-bis).

Con un reloj falso: la ventana se prueba moviendo el tiempo, no durmiendo.
"""

from app.common.rate_limit import FixedWindowLimiter


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_lets_through_up_to_the_limit_then_says_how_long_to_wait() -> None:
    clock = _Clock()
    limiter = FixedWindowLimiter(limit=3, window_seconds=60, clock=clock)
    assert [limiter.hit("ip") for _ in range(3)] == [None, None, None]
    clock.now += 20
    assert limiter.hit("ip") == 40


def test_the_window_resets_and_keys_are_independent() -> None:
    clock = _Clock()
    limiter = FixedWindowLimiter(limit=1, window_seconds=60, clock=clock)
    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None
    assert limiter.hit("b") is None  # otra IP u otro token: su propio cupo
    clock.now += 60
    assert limiter.hit("a") is None


def test_a_rejected_request_does_not_extend_the_penalty() -> None:
    """Quien insiste bloqueado solo espera a que termine SU ventana: si los
    rechazos contaran, un cliente que reintenta en bucle no saldría nunca."""
    clock = _Clock()
    limiter = FixedWindowLimiter(limit=1, window_seconds=60, clock=clock)
    limiter.hit("a")
    for _ in range(50):
        clock.now += 1
        limiter.hit("a")
    clock.now += 10  # 60 s desde el primer pedido
    assert limiter.hit("a") is None


def test_memory_is_bounded_when_every_request_brings_a_new_key() -> None:
    """Una IP que manda un token distinto en cada pedido crea una llave por
    pedido. Al tope se barren las vencidas, y si no alcanza, se vacía."""
    clock = _Clock()
    limiter = FixedWindowLimiter(limit=5, window_seconds=60, max_keys=100, clock=clock)
    for i in range(100):
        limiter.hit(f"k{i}")
    clock.now += 61
    limiter.hit("nueva")  # las 100 vencieron: se barren, entra la nueva
    assert len(limiter._hits) == 1
    for i in range(150):
        limiter.hit(f"x{i}")
    assert len(limiter._hits) <= 100
