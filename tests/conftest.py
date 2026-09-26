import os

# Deben fijarse ANTES de importar cualquier módulo de `app`: app.core.db crea el
# engine al importarse, y Settings() exige estas variables.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
)
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_JWKS_URL", "http://127.0.0.1:54321/auth/v1/.well-known/jwks.json")
os.environ.setdefault("JWT_AUDIENCE", "authenticated")
os.environ.setdefault("ENVIRONMENT", "test")
# Asignación, no `setdefault`: una key real en el `.env` o en la shell de quien
# corre la suite NO debe mandar correos desde los tests. Con esto vacío el
# despachador cae en el proveedor nulo; los tests que quieren "enviar"
# inyectan un `RecordingProvider` explícito.
os.environ["RESEND_API_KEY"] = ""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _generate_rsa_keypair() -> tuple[str, object]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return private_pem, private_key.public_key()


@pytest.fixture
def rsa_keypair() -> tuple[str, object]:
    return _generate_rsa_keypair()


@pytest.fixture
def rsa_keypair_other() -> tuple[str, object]:
    return _generate_rsa_keypair()


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    """El límite de tasa del endpoint público de baja vive en memoria del
    proceso (`app/common/rate_limit.py`), y la suite entera corre en uno solo
    desde la misma IP de `TestClient`: sin esto, el test número 61 que abre
    un enlace de baja recibiría un 429 por culpa de los otros sesenta."""
    from app.common import rate_limit

    rate_limit.reset_all()
