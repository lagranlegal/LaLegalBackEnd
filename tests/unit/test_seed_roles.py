from app.modules.platform.service import build_seed_role_permissions

# Los 25 códigos exactos de supabase/seed.sql — si el seed cambia, este test
# debe actualizarse a la par (evita que la matriz de roles semilla quede
# desincronizada del catálogo real sin que nadie se dé cuenta).
_SEED_PERMISSION_CODES = {
    "contracts.view",
    "contracts.create",
    "contracts.edit",
    "contracts.auction",
    "contracts.import",
    "payments.create",
    "payments.apply_discount",
    "customers.view",
    "customers.create",
    "catalogs.manage",
    "inventory.view",
    "inventory.create",
    "inventory.exit",
    "sales.create",
    "sales.void",
    "sales.apply_discount",
    "cashbox.view",
    "cashbox.open_close",
    "cashbox.reopen",
    "cashbox.expense",
    "identity.manage_users",
    "identity.manage_roles",
    "reports.view",
    "audit.view",
    "company.configure",
}


def test_seed_matrix_covers_exactly_four_roles() -> None:
    matrix = build_seed_role_permissions(_SEED_PERMISSION_CODES)
    assert set(matrix.keys()) == {"Admin", "Moderador", "Asesor", "Bodega"}


def test_admin_has_every_permission() -> None:
    matrix = build_seed_role_permissions(_SEED_PERMISSION_CODES)
    assert matrix["Admin"] == _SEED_PERMISSION_CODES


def test_moderador_excludes_exactly_the_documented_codes() -> None:
    matrix = build_seed_role_permissions(_SEED_PERMISSION_CODES)
    excluded = _SEED_PERMISSION_CODES - matrix["Moderador"]
    assert excluded == {
        "inventory.create",
        "inventory.exit",
        "identity.manage_users",
        "identity.manage_roles",
        "cashbox.open_close",
        "cashbox.reopen",
        "payments.apply_discount",
        "sales.apply_discount",
        "audit.view",
        "company.configure",
        "contracts.import",
    }


def test_asesor_matches_documented_codes() -> None:
    matrix = build_seed_role_permissions(_SEED_PERMISSION_CODES)
    assert matrix["Asesor"] == {
        "contracts.view",
        "contracts.create",
        "payments.create",
        "customers.view",
        "customers.create",
        "inventory.view",
        "sales.create",
        "cashbox.view",
    }


def test_bodega_matches_documented_codes() -> None:
    matrix = build_seed_role_permissions(_SEED_PERMISSION_CODES)
    assert matrix["Bodega"] == {
        "inventory.view",
        "inventory.create",
        "catalogs.manage",
        "customers.view",
    }


def test_moderador_never_has_admin_permission() -> None:
    matrix = build_seed_role_permissions(_SEED_PERMISSION_CODES)
    assert "identity.manage_roles" not in matrix["Moderador"]
    assert "identity.manage_roles" not in matrix["Asesor"]
    assert "identity.manage_roles" not in matrix["Bodega"]
