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
