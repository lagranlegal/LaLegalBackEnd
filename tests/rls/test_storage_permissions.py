"""Storage: cada archivo se lee y escribe con el permiso de su sección (00062).

Auditoría del 27/09/2026, F3-03: la política de `storage.objects` solo miraba
la carpeta de la empresa, así que cualquier usuario de la empresa —con el
permiso que fuera— leía, subía y borraba fotos de cédulas de clientes. Desde
00062 decide `public.storage_object_allowed(bucket, ruta, escribir)`, y las
cuatro políticas del bucket solo la llaman.

Se prueba la FUNCIÓN, evaluada como `authenticated` con los claims del JWT
—exactamente como la evalúa el gateway de Storage—, porque el Postgres local
y el de CI no traen el servicio de Storage (`storage.objects` no existe; ver
la guarda de 00013). Donde sí existe, el último test verifica que las
políticas la usen.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.db import AsyncSessionLocal, apply_tenant_claims, engine


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


_USUARIOS = {
    "sin_permisos": ([], "active"),
    "ve_clientes": (["customers.view"], "active"),
    "gestiona_clientes": (["customers.view", "customers.create"], "active"),
    "inventario": (["inventory.view"], "active"),
    "configura": (["company.configure"], "active"),
    "inactivo": (["customers.view", "customers.create"], "inactive"),
}


@pytest_asyncio.fixture
async def empresas() -> AsyncGenerator[dict, None]:
    company_a, company_b = uuid.uuid4(), uuid.uuid4()
    usuarios: dict[str, uuid.UUID] = {}
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, :name)"),
            [
                {"id": str(company_a), "name": "Storage A (test)"},
                {"id": str(company_b), "name": "Storage B (test)"},
            ],
        )
        for nombre, (codes, estado) in _USUARIOS.items():
            role_id, user_id = uuid.uuid4(), uuid.uuid4()
            await session.execute(
                text("insert into public.role (id, company_id, name) values (:id, :cid, :n)"),
                {"id": str(role_id), "cid": str(company_a), "n": nombre},
            )
            await session.execute(
                text(
                    "insert into public.role_permission (role_id, permission_id) "
                    "select :rid, id from public.permission where code = any(:codes)"
                ),
                {"rid": str(role_id), "codes": codes},
            )
            await session.execute(
                text(
                    "insert into public.app_user (id, company_id, role_id, full_name, email, "
                    "status) values (:id, :cid, :rid, :n, :email, :status)"
                ),
                {
                    "id": str(user_id),
                    "cid": str(company_a),
                    "rid": str(role_id),
                    "n": nombre,
                    "email": f"{nombre}-{user_id}@example.com",
                    "status": estado,
                },
            )
            usuarios[nombre] = user_id

    yield {"a": company_a, "b": company_b, "usuarios": usuarios}

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("delete from public.app_user where company_id = :id"), {"id": str(company_a)}
        )
        await session.execute(
            text(
                "delete from public.role_permission where role_id in "
                "(select id from public.role where company_id = :id)"
            ),
            {"id": str(company_a)},
        )
        await session.execute(
            text("delete from public.role where company_id = :id"), {"id": str(company_a)}
        )
        await session.execute(
            text("delete from public.company where id = any(:ids)"),
            {"ids": [str(company_a), str(company_b)]},
        )


async def _permitido(
    user_id: uuid.UUID, company_id: uuid.UUID, ruta: str, *, escribir: bool
) -> bool:
    async with AsyncSessionLocal() as session, session.begin():
        await apply_tenant_claims(session, {"sub": str(user_id), "company_id": str(company_id)})
        return bool(
            (
                await session.execute(
                    text("select public.storage_object_allowed('company-files', :ruta, :w)"),
                    {"ruta": ruta, "w": escribir},
                )
            ).scalar_one()
        )


async def test_fotos_de_clientes_exigen_customers_view_para_leer_y_create_para_escribir(
    empresas: dict,
) -> None:
    a, u = empresas["a"], empresas["usuarios"]
    ruta = f"{a}/customers/{uuid.uuid4()}/foto.webp"

    assert await _permitido(u["sin_permisos"], a, ruta, escribir=False) is False
    assert await _permitido(u["sin_permisos"], a, ruta, escribir=True) is False
    assert await _permitido(u["ve_clientes"], a, ruta, escribir=False) is True
    assert await _permitido(u["ve_clientes"], a, ruta, escribir=True) is False
    assert await _permitido(u["gestiona_clientes"], a, ruta, escribir=True) is True


async def test_un_usuario_inactivo_no_abre_nada_aunque_su_token_siga_vivo(
    empresas: dict,
) -> None:
    a, u = empresas["a"], empresas["usuarios"]
    ruta = f"{a}/customers/x/foto.webp"
    assert await _permitido(u["inactivo"], a, ruta, escribir=False) is False
    assert await _permitido(u["inactivo"], a, f"{a}/company/logo/l.webp", escribir=False) is False


async def test_la_carpeta_de_otra_empresa_sigue_cerrada(empresas: dict) -> None:
    a, b, u = empresas["a"], empresas["b"], empresas["usuarios"]
    ruta_b = f"{b}/customers/x/foto.webp"
    assert await _permitido(u["gestiona_clientes"], a, ruta_b, escribir=False) is False
    assert await _permitido(u["gestiona_clientes"], a, ruta_b, escribir=True) is False


async def test_logo_y_firma_los_lee_cualquiera_y_los_escribe_company_configure(
    empresas: dict,
) -> None:
    a, u = empresas["a"], empresas["usuarios"]
    logo = f"{a}/company/logo/l.webp"
    assert await _permitido(u["sin_permisos"], a, logo, escribir=False) is True
    assert await _permitido(u["sin_permisos"], a, logo, escribir=True) is False
    assert await _permitido(u["configura"], a, logo, escribir=True) is True


async def test_las_fotos_de_la_prenda_las_ve_tambien_inventario(empresas: dict) -> None:
    """El remate copia las rutas de `contract-items/` al artículo de inventario."""
    a, u = empresas["a"], empresas["usuarios"]
    prenda = f"{a}/contract-items/x/p.webp"
    assert await _permitido(u["inventario"], a, prenda, escribir=False) is True
    assert await _permitido(u["inventario"], a, prenda, escribir=True) is False
    assert await _permitido(u["ve_clientes"], a, prenda, escribir=False) is False
    assert await _permitido(u["inventario"], a, f"{a}/inventory/i/f.webp", escribir=False) is True


async def test_una_seccion_desconocida_o_sin_seccion_se_niega(empresas: dict) -> None:
    a, u = empresas["a"], empresas["usuarios"]
    assert await _permitido(u["gestiona_clientes"], a, f"{a}/otra/x.webp", escribir=False) is False
    assert await _permitido(u["gestiona_clientes"], a, f"{a}/x.webp", escribir=False) is False


async def test_las_politicas_del_bucket_usan_la_funcion() -> None:
    async with AsyncSessionLocal() as session:
        existe = (
            await session.execute(text("select to_regclass('storage.objects') is not null"))
        ).scalar_one()
        if not existe:
            pytest.skip("Sin servicio de Storage (storage.objects no existe): igual que en CI.")
        filas = (
            await session.execute(
                text(
                    "select policyname, coalesce(qual, '') || coalesce(with_check, '') "
                    "from pg_policies where schemaname = 'storage' and tablename = 'objects'"
                )
            )
        ).all()
    politicas = dict((r[0], r[1]) for r in filas)
    assert "tenant_isolation" not in politicas
    for nombre in ("select", "insert", "update", "delete"):
        assert "storage_object_allowed" in politicas[f"company_files_{nombre}"]
