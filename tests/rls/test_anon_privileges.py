"""El rol `anon` no tiene privilegios en el esquema `public` (00064).

Toda la app entra con sesión (`authenticated`); `anon` no lee, no escribe
y no ejecuta nada de `public`. El hook de claims solo lo ejecuta Supabase
Auth. Se mira el catálogo completo, así una tabla o función nueva que nazca
con privilegios para `anon` rompe este test.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.db import engine


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


async def _rows(sql: str) -> list[tuple]:
    async with engine.connect() as conn:
        return [tuple(r) for r in (await conn.execute(text(sql))).all()]


async def test_anon_has_no_table_or_sequence_privileges_in_public() -> None:
    tables = await _rows(
        """
        select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind in ('r', 'v', 'm', 'p')
          and has_table_privilege(
                'anon', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        """
    )
    sequences = await _rows(
        """
        with seqs as materialized (
            select c.oid, c.relname from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind = 'S'
        )
        select relname from seqs
        where has_sequence_privilege('anon', oid, 'USAGE,SELECT,UPDATE')
        """
    )
    assert tables == []
    assert sequences == []


async def test_authenticated_keeps_its_table_privileges() -> None:
    missing = await _rows(
        """
        select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r'
          and not has_table_privilege('authenticated', c.oid, 'SELECT')
        """
    )
    assert missing == []


async def test_anon_cannot_execute_any_function_in_public() -> None:
    functions = await _rows(
        """
        select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and has_function_privilege('anon', p.oid, 'EXECUTE')
        """
    )
    assert functions == []


async def test_permission_helpers_are_for_authenticated_only() -> None:
    for signature in (
        "public.current_user_has_permission(text)",
        "public.current_user_is_active_member()",
        "public.storage_object_allowed(text, text, boolean)",
    ):
        (row,) = await _rows(
            f"select has_function_privilege('anon', '{signature}', 'EXECUTE'),"
            f" has_function_privilege('authenticated', '{signature}', 'EXECUTE')"
        )
        assert row == (False, True), signature


async def test_claims_hook_is_only_executable_by_supabase_auth() -> None:
    signature = "public.custom_access_token_hook(jsonb)"
    (row,) = await _rows(
        f"select has_function_privilege('anon', '{signature}', 'EXECUTE'),"
        f" has_function_privilege('authenticated', '{signature}', 'EXECUTE'),"
        f" has_function_privilege('supabase_auth_admin', '{signature}', 'EXECUTE')"
    )
    assert row == (False, False, True)


async def test_future_objects_do_not_grant_anon() -> None:
    acls = await _rows(
        """
        select a.defaclobjtype, a.defaclacl::text from pg_default_acl a
        join pg_namespace n on n.oid = a.defaclnamespace
        where n.nspname = 'public' and a.defaclrole = 'postgres'::regrole
        """
    )
    assert acls, "se esperan default privileges para postgres en public"
    for objtype, acl in acls:
        assert "anon=" not in acl, (objtype, acl)
        if objtype == "f":
            # Sin entrada `=X/...`: las funciones nuevas no se ejecutan por PUBLIC.
            assert not acl.startswith("{=") and ",=" not in acl, acl
