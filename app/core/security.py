from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from cachetools import TTLCache
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import apply_tenant_claims, get_db
from app.core.errors import PermissionDeniedError, SubscriptionExpiredError, UnauthorizedError
from app.core.settings import get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_jwk_client() -> PyJWKClient:
    return PyJWKClient(get_settings().supabase_jwks_url)


@dataclass(frozen=True)
class TokenClaims:
    sub: UUID
    company_id: UUID | None
    role_id: UUID | None
    raw: dict[str, Any]


def decode_token(token: str) -> TokenClaims:
    settings = get_settings()
    try:
        signing_key = get_jwk_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.jwt_audience,
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Token inválido o expirado.") from exc

    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Token sin 'sub'.")

    company_id = payload.get("company_id")
    role_id = payload.get("role_id")
    return TokenClaims(
        sub=UUID(sub),
        company_id=UUID(company_id) if company_id else None,
        role_id=UUID(role_id) if role_id else None,
        raw=payload,
    )


async def get_verified_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> TokenClaims:
    if credentials is None:
        raise UnauthorizedError("Falta el header Authorization: Bearer <token>.")
    claims = decode_token(credentials.credentials)
    if claims.company_id is None or claims.role_id is None:
        # El Custom Access Token Hook no emitió claims de tenant:
        # usuario inactivo o empresa suspendida (00003_identity.sql).
        raise UnauthorizedError("La cuenta no tiene acceso activo a ninguna empresa.")
    return claims


async def get_tenant_db(
    claims: Annotated[TokenClaims, Depends(get_verified_claims)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncSession:
    await apply_tenant_claims(db, claims.raw)
    return db


async def require_super_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> TokenClaims:
    """Plataforma (empresas/suscripciones): no hay tabla de super-admins en el
    esquema. Se marca una sola vez, fuera de la app, con
    `app_metadata.platform_role = "super_admin"` en Supabase Auth — Supabase
    incluye `app_metadata` en el JWT por defecto, sin pasar por el Custom
    Access Token Hook ni por RLS.

    OJO: NO depende de `get_verified_claims` — un super-admin no tiene fila en
    `app_user`, así que nunca va a traer `company_id`/`role_id` en el token, y
    `get_verified_claims` lo rechazaría por eso. Aquí solo se valida la firma
    del JWT (`decode_token`) y el claim de plataforma.
    """
    if credentials is None:
        raise UnauthorizedError("Falta el header Authorization: Bearer <token>.")
    claims = decode_token(credentials.credentials)
    if claims.raw.get("app_metadata", {}).get("platform_role") != "super_admin":
        raise PermissionDeniedError("Requiere rol de super-admin de plataforma.")
    return claims


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    company_id: UUID
    role_id: UUID
    full_name: str
    email: str


# Cache corto (CLAUDE.md: "cache corto") para no repegar app_user/company/subscription
# en cada request. Se invalida sola por TTL; no hay invalidación activa en este esqueleto.
_current_user_cache: TTLCache[UUID, CurrentUser] = TTLCache(maxsize=2048, ttl=30)


def _sesion_con_contrasena(claims: TokenClaims) -> bool:
    """¿Esta sesión nació de un login con contraseña?

    `amr` viene así en el token de Supabase:

        login normal      → [{"method": "password", ...}]
        enlace/invitación → [{"method": "otp", ...}]

    Se mira el método y no la ausencia de `otp` para que cualquier método
    futuro (SSO, passkey) tenga que declararse a propósito en vez de colarse.
    """
    amr = claims.raw.get("amr")
    if not isinstance(amr, list):
        return False
    return any(isinstance(m, dict) and m.get("method") == "password" for m in amr)


async def get_current_user(
    claims: Annotated[TokenClaims, Depends(get_verified_claims)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CurrentUser:
    cached = _current_user_cache.get(claims.sub)
    if cached is not None:
        return cached

    row = (
        (
            await db.execute(
                text(
                    """
                select au.id, au.company_id, au.role_id, au.full_name, au.email,
                       au.status as user_status,
                       c.status as company_status,
                       s.status as subscription_status, s.expires_at
                from public.app_user au
                join public.company c on c.id = au.company_id
                left join public.subscription s
                       on s.company_id = au.company_id and s.status = 'active'
                where au.id = :user_id
                """
                ),
                {"user_id": str(claims.sub)},
            )
        )
        .mappings()
        .first()
    )

    if row is None or row["company_status"] != "active":
        raise UnauthorizedError("Usuario o empresa inactivos.")
    if row["user_status"] == "invited":
        # Se activa SOLO si entró con su propia contraseña, no con cualquier
        # JWT válido.
        #
        # BUG REAL (04/09/2026): acá decía "si llegó con un JWT válido ya
        # completó la invitación (puso contraseña)". Es falso — abrir el
        # enlace de invitación YA produce un JWT válido, antes de que exista
        # ninguna contraseña. Comprobado: canjear el enlace y hacer un solo
        # request dejaba al usuario en `active` sin haber puesto nunca una
        # clave, y después no podía entrar (Supabase devuelve 400). El admin
        # veía "Activo" en la lista —todo en orden— mientras esa persona
        # estaba bloqueada para siempre, y nada en la pantalla lo delataba.
        #
        # `amr` (Authentication Methods References) distingue exactamente los
        # dos casos: `otp` cuando la sesión viene de un enlace, `password`
        # cuando viene de un login de verdad. Con esto, `active` pasa a
        # significar lo único que le sirve al admin: **esta persona ya puede
        # entrar por su cuenta**.
        #
        # Al invitado se le deja pasar igual mientras siga `invited`: esa
        # sesión del enlace es legítima y es justamente la que necesita para
        # poner su contraseña.
        if _sesion_con_contrasena(claims):
            await db.execute(
                text("update public.app_user set status = 'active' where id = :user_id"),
                {"user_id": str(claims.sub)},
            )
    elif row["user_status"] != "active":
        raise UnauthorizedError("Usuario o empresa inactivos.")
    if row["subscription_status"] != "active":
        raise SubscriptionExpiredError("La suscripción de la empresa no está vigente.")

    user = CurrentUser(
        id=row["id"],
        company_id=row["company_id"],
        role_id=row["role_id"],
        full_name=row["full_name"],
        email=row["email"],
    )
    _current_user_cache[claims.sub] = user
    return user


# Cache corto TTL 60s por rol (CLAUDE.md, sección Roles y permisos).
_role_permissions_cache: TTLCache[UUID, frozenset[str]] = TTLCache(maxsize=1024, ttl=60)


async def _load_role_permissions(db: AsyncSession, role_id: UUID) -> frozenset[str]:
    cached = _role_permissions_cache.get(role_id)
    if cached is not None:
        return cached

    rows = await db.execute(
        text(
            """
            select p.code
            from public.role_permission rp
            join public.permission p on p.id = rp.permission_id
            where rp.role_id = :role_id
            """
        ),
        {"role_id": str(role_id)},
    )
    codes = frozenset(row[0] for row in rows)
    _role_permissions_cache[role_id] = codes
    return codes


def require_permission(code: str) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    async def _check(
        user: Annotated[CurrentUser, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_tenant_db)],
    ) -> CurrentUser:
        permissions = await _load_role_permissions(db, user.role_id)
        if code not in permissions:
            raise PermissionDeniedError(f"Falta el permiso '{code}'.", details={"permission": code})
        return user

    return _check


async def has_permission(db: AsyncSession, role_id: UUID, code: str) -> bool:
    """Chequeo puntual reutilizable fuera de un `Depends` — para permisos
    *condicionales* dentro de un service (ej. `payments.apply_discount` solo
    si el abono trae descuento). Usa el mismo cache que `require_permission`.
    """
    permissions = await _load_role_permissions(db, role_id)
    return code in permissions


async def get_role_permissions(db: AsyncSession, role_id: UUID) -> list[str]:
    """Lista completa de códigos de permiso de un rol — para `GET /me`, así
    el front sabe exactamente qué puede hacer sin ir probando y recibiendo
    403. Mismo cache (TTL 60s) que `require_permission`/`has_permission`:
    lo que devuelve acá es exactamente lo que el backend va a aceptar.
    """
    permissions = await _load_role_permissions(db, role_id)
    return sorted(permissions)
