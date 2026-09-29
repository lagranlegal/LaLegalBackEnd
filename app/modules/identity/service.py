import math
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.common.rate_limit import RateLimitedError
from app.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.security import CurrentUser
from app.core.security import get_role_permissions as get_cached_role_permissions
from app.core.settings import get_settings
from app.modules.identity import auth_admin, integration, repository
from app.modules.identity.schemas import (
    InvitedUserOut,
    MeCompanyOut,
    MeDocumentsOut,
    MeOut,
    MePlanOut,
    MeRoleOut,
    MeSubscriptionOut,
    MeUpdateIn,
    MeUserOut,
    PermissionOut,
    RecoveryLinkOut,
    RoleOut,
    UserOut,
)
from app.modules.platform import repository as platform_repo

_ADMIN_PERMISSION = "identity.manage_roles"


def _row_to_user(row: Row[Any]) -> UserOut:
    m = row._mapping
    return UserOut(
        id=m["id"],
        full_name=m["full_name"],
        email=m["email"],
        role_id=m["role_id"],
        status=m["status"],
        created_at=m["created_at"],
    )


def _row_to_role(row: Row[Any]) -> RoleOut:
    m = row._mapping
    return RoleOut(
        id=m["id"],
        name=m["name"],
        description=m["description"],
        is_seed=m["is_seed"],
        active=m["active"],
        # Solo `list_roles` trae la cuenta; `get_role` no la necesita y no la
        # selecciona, así que se lee con `.get` en vez de asumirla presente.
        permission_count=m.get("permission_count", 0),
    )


async def _actor_permission_codes(db: AsyncSession, actor_role_id: UUID) -> set[str]:
    """Permisos del rol de quien actúa, leídos de la base y NO del caché.

    El caché de `require_permission` (TTL 60 s) basta para decidir si alguien
    entra a un endpoint; para decidir qué puede OTORGAR se lee la fila vigente,
    así un rol recortado hace un segundo ya no reparte lo que perdió.
    """
    return set(await repository.role_permission_codes(db, role_id=actor_role_id))


def _ensure_within_actor(codes: set[str], actor_codes: set[str], *, message: str) -> None:
    """Quien gestiona usuarios o roles solo reparte permisos que él mismo tiene.

    Es la regla que hace que `identity.manage_users` sea lo que su nombre dice
    —gestionar las cuentas de la gente— y no un atajo a cualquier rol de la
    empresa: asignar, invitar, generar un enlace de acceso o editar un rol
    exige que los permisos en juego sean un subconjunto de los del actor
    (auditoría 27/09/2026, F3-02). Un administrador con el catálogo completo
    no nota ninguna diferencia.

    `details.missing_permissions` lista lo que le falta al actor, para que la
    pantalla pueda decir cuál y no solo "no se puede".
    """
    missing = codes - actor_codes
    if missing:
        raise PermissionDeniedError(
            message,
            details={"missing_permissions": sorted(missing)},
            code="ROLE_EXCEEDS_ACTOR_PERMISSIONS",
        )


async def _ensure_role_within_actor(
    db: AsyncSession, *, role_id: UUID, actor_role_id: UUID, message: str
) -> None:
    codes = set(await repository.role_permission_codes(db, role_id=role_id))
    _ensure_within_actor(codes, await _actor_permission_codes(db, actor_role_id), message=message)


async def list_users(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[UserOut]:
    rows = await repository.list_users(db, company_id=company_id, cursor=cursor, limit=limit)
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_user(r) for r in page.items], next_cursor=page.next_cursor)


class InvitationsRateLimitedError(RateLimitedError):
    code = "INVITATIONS_RATE_LIMITED"


async def _ensure_invitation_quota(db: AsyncSession, *, company_id: UUID) -> None:
    """Tope por empresa de invitaciones + enlaces de acceso (settings
    `invitations_per_hour` / `invitations_per_day`). Se revisa antes de pedirle
    nada a Supabase Auth: un pedido rechazado no genera ningún enlace."""
    settings = get_settings()
    last_hour, last_day, hour_wait, day_wait = await repository.invitation_activity(
        db, company_id=company_id
    )
    if last_day >= settings.invitations_per_day:
        wait = day_wait
    elif last_hour >= settings.invitations_per_hour:
        wait = hour_wait
    else:
        return
    retry_after = max(1, math.ceil(wait or 0))
    raise InvitationsRateLimitedError(
        "Se alcanzó el límite de invitaciones y enlaces de acceso de la empresa "
        f"({settings.invitations_per_hour} por hora, {settings.invitations_per_day} "
        "por día). Intenta de nuevo más tarde.",
        retry_after_seconds=retry_after,
    )


async def invite_user(
    db: AsyncSession,
    *,
    company_id: UUID,
    role_id: UUID,
    email: str,
    full_name: str,
    invited_by: UUID,
    acting_role_id: UUID,
    send_email: bool = True,
) -> tuple[InvitedUserOut, integration.InvitationEmail | None]:
    """Devuelve también el correo a mandar después del commit (§16): el router
    lo agenda en un `BackgroundTasks`. El enlace que lleva es una credencial y
    no pasa por la respuesta."""
    role = await repository.get_role(db, company_id=company_id, role_id=role_id)
    if role is None:
        raise NotFoundError("El rol indicado no existe en esta empresa.")
    await _ensure_role_within_actor(
        db,
        role_id=role_id,
        actor_role_id=acting_role_id,
        message="No puedes invitar a alguien con un rol que tiene permisos que tú no tienes.",
    )

    # Invitar dos veces al mismo correo es lo NORMAL: "el enlace no le llegó,
    # mándaselo otra vez". Sin esta comprobación el segundo intento reventaba
    # el índice único de `app_user` y salía un **500 en texto plano** (ni
    # siquiera el envelope de error), que el front muestra como "Ocurrió un
    # error inesperado". Y encima Supabase ya había regenerado el enlace, así
    # que el primero —el que el admin quizá ya mandó por WhatsApp— quedaba
    # muerto sin que nadie lo supiera.
    #
    # La acción correcta no es invitar de nuevo: es generar el enlace desde la
    # ficha de esa persona, que es lo que dice el mensaje.
    existente = await repository.find_user_by_email(db, company_id=company_id, email=email)
    if existente is not None:
        estado = existente._mapping["status"]
        if estado == "invited":
            raise ConflictError(
                "Ya invitaste a esta persona y todavía no ha entrado. Para volver a "
                "darle acceso, abre su ficha en Usuarios y usa «Generar enlace de "
                "activación» — invitarla otra vez anularía el enlace anterior.",
                code="USER_ALREADY_INVITED",
            )
        if estado == "inactive":
            raise ConflictError(
                "Esta persona ya existe en la empresa pero está inactiva. "
                "Reactívala desde su ficha en Usuarios en vez de invitarla de nuevo.",
                code="USER_ALREADY_EXISTS",
            )
        raise ConflictError(
            "Ya hay un usuario activo con ese correo en esta empresa.",
            code="USER_ALREADY_EXISTS",
        )

    await _ensure_invitation_quota(db, company_id=company_id)
    result = await integration.invite_user(
        db,
        company_id=company_id,
        role_id=role_id,
        email=email,
        full_name=full_name,
        invited_by=invited_by,
        send_email=send_email,
    )
    row = await repository.get_user(db, company_id=company_id, user_id=result.user_id)
    assert row is not None
    out = InvitedUserOut(
        **_row_to_user(row).model_dump(),
        invite_link=result.admin_link,
        invite_delivery=result.delivery,
    )
    return out, result.email


async def _role_has_admin_permission(db: AsyncSession, role_id: UUID) -> bool:
    codes = await repository.role_permission_codes(db, role_id=role_id)
    return _ADMIN_PERMISSION in codes


async def update_user_role(
    db: AsyncSession,
    *,
    company_id: UUID,
    user_id: UUID,
    new_role_id: UUID,
    acting_user_id: UUID,
    acting_role_id: UUID,
) -> UserOut:
    # Nadie cambia su propio rol: ni para subirlo ni para bajarlo. Un cambio de
    # rol es una decisión que toma OTRA persona y queda auditada a su nombre
    # (F3-02). Se valida antes del candado: no hay nada que contar.
    if user_id == acting_user_id:
        raise PermissionDeniedError(
            "No puedes cambiar tu propio rol. Pídeselo a otra persona que gestione usuarios.",
            code="CANNOT_CHANGE_OWN_ROLE",
        )
    # F3-07: antes de leer nada, el candado de la salvaguarda del último admin.
    await repository.lock_admin_safeguard(db, company_id=company_id)
    user = await repository.get_user(db, company_id=company_id, user_id=user_id)
    if user is None:
        raise NotFoundError("El usuario no existe en esta empresa.")
    new_role = await repository.get_role(db, company_id=company_id, role_id=new_role_id)
    if new_role is None:
        raise NotFoundError("El rol indicado no existe en esta empresa.")

    old_role_id = user._mapping["role_id"]
    # Las dos puntas: el rol que se entrega Y el que la persona tiene hoy. Si
    # solo se mirara el nuevo, quien gestiona usuarios podría cambiarle el rol
    # a alguien con más permisos que él —quitárselos—, y eso también es
    # decidir sobre permisos que no le pertenecen.
    actor_codes = await _actor_permission_codes(db, acting_role_id)
    _ensure_within_actor(
        set(await repository.role_permission_codes(db, role_id=new_role_id)),
        actor_codes,
        message="No puedes asignar un rol que tiene permisos que tú no tienes.",
    )
    _ensure_within_actor(
        set(await repository.role_permission_codes(db, role_id=old_role_id)),
        actor_codes,
        message="No puedes cambiarle el rol a alguien que tiene permisos que tú no tienes.",
    )
    if old_role_id != new_role_id and await _role_has_admin_permission(db, old_role_id):
        if not await _role_has_admin_permission(db, new_role_id):
            remaining = await repository.count_active_admins(
                db, company_id=company_id, exclude_user_id=user_id
            )
            if remaining == 0:
                raise ConflictError(
                    "No se puede quitar el último administrador activo de la empresa.",
                    code="LAST_ADMIN_SAFEGUARD",
                )

    await repository.update_user_role(
        db, company_id=company_id, user_id=user_id, role_id=new_role_id
    )
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="update_user_role",
        entity_type="app_user",
        entity_id=user_id,
        before={"role_id": str(old_role_id)},
        after={"role_id": str(new_role_id)},
    )
    row = await repository.get_user(db, company_id=company_id, user_id=user_id)
    assert row is not None
    return _row_to_user(row)


async def _set_user_active_status(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, active: bool, acting_user_id: UUID
) -> None:
    if not active:
        # F3-07: desactivar puede dejar la empresa sin admins; reactivar no.
        await repository.lock_admin_safeguard(db, company_id=company_id)
    user = await repository.get_user(db, company_id=company_id, user_id=user_id)
    if user is None:
        raise NotFoundError("El usuario no existe en esta empresa.")

    # NADIE SE DESACTIVA A SÍ MISMO. La UI ya lo oculta, pero ocultar no es
    # proteger (CLAUDE.md regla 7): sin esto, un admin que no sea el último
    # podía dejarse fuera de su propia empresa con un request a mano, y la
    # única salida sería que otro lo reactivara.
    if not active and user_id == acting_user_id:
        raise ConflictError(
            "No puedes desactivar tu propia cuenta. Si te vas de la empresa, "
            "pídele a otro administrador que lo haga.",
            code="CANNOT_DEACTIVATE_SELF",
        )

    if not active and await _role_has_admin_permission(db, user._mapping["role_id"]):
        remaining = await repository.count_active_admins(
            db, company_id=company_id, exclude_user_id=user_id
        )
        if remaining == 0:
            raise ConflictError(
                "No se puede inactivar al último administrador activo de la empresa.",
                code="LAST_ADMIN_SAFEGUARD",
            )

    current_status = user._mapping["status"]
    if not active:
        new_status = "inactive"
    elif current_status != "inactive":
        # Reactivar a quien no está inactivo no cambia nada: un invitado sigue
        # invitado hasta que entre con su propia contraseña.
        new_status = current_status
    else:
        # Reactivar devuelve al estado que tenía antes de desactivarlo. Quien
        # nunca completó su invitación vuelve a `invited`, no a `active`:
        # `active` significa "ya puede entrar por su cuenta" (ver
        # `get_current_user`), y esa persona todavía no tiene contraseña.
        previous = await repository.status_before_last_deactivation(
            db, company_id=company_id, user_id=user_id
        )
        new_status = "invited" if previous == "invited" else "active"

    if new_status == current_status:
        return
    await repository.set_user_status(db, company_id=company_id, user_id=user_id, status=new_status)
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="reactivate_user" if active else "deactivate_user",
        entity_type="app_user",
        entity_id=user_id,
        before={"status": current_status},
        after={"status": new_status},
    )


async def deactivate_user(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, acting_user_id: UUID
) -> None:
    await _set_user_active_status(
        db, company_id=company_id, user_id=user_id, active=False, acting_user_id=acting_user_id
    )


async def reactivate_user(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, acting_user_id: UUID
) -> None:
    await _set_user_active_status(
        db, company_id=company_id, user_id=user_id, active=True, acting_user_id=acting_user_id
    )


async def list_roles(db: AsyncSession, *, company_id: UUID) -> list[RoleOut]:
    rows = await repository.list_roles(db, company_id=company_id)
    return [_row_to_role(r) for r in rows]


async def create_role(
    db: AsyncSession,
    *,
    company_id: UUID,
    name: str,
    description: str | None,
    clone_from_role_id: UUID | None,
    acting_user_id: UUID,
    acting_role_id: UUID,
) -> RoleOut:
    if clone_from_role_id is not None:
        source = await repository.get_role(db, company_id=company_id, role_id=clone_from_role_id)
        if source is None:
            raise NotFoundError("El rol a clonar no existe en esta empresa.")
        # Clonar es crear un rol con esos permisos: misma regla que editarlos.
        await _ensure_role_within_actor(
            db,
            role_id=clone_from_role_id,
            actor_role_id=acting_role_id,
            message="No puedes clonar un rol que tiene permisos que tú no tienes.",
        )

    role_id = uuid4()
    await repository.insert_role(
        db, role_id=role_id, company_id=company_id, name=name, description=description
    )
    if clone_from_role_id is not None:
        await repository.copy_role_permissions(
            db, source_role_id=clone_from_role_id, target_role_id=role_id
        )
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="create_role",
        entity_type="role",
        entity_id=role_id,
        after={"name": name, "clone_from_role_id": str(clone_from_role_id or "")},
    )
    row = await repository.get_role(db, company_id=company_id, role_id=role_id)
    assert row is not None
    return _row_to_role(row)


async def rename_role(
    db: AsyncSession,
    *,
    company_id: UUID,
    role_id: UUID,
    name: str,
    description: str | None,
    acting_user_id: UUID,
) -> RoleOut:
    role = await repository.get_role(db, company_id=company_id, role_id=role_id)
    if role is None:
        raise NotFoundError("El rol no existe en esta empresa.")
    await repository.update_role_name(
        db, company_id=company_id, role_id=role_id, name=name, description=description
    )
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="rename_role",
        entity_type="role",
        entity_id=role_id,
        before={"name": role._mapping["name"]},
        after={"name": name},
    )
    row = await repository.get_role(db, company_id=company_id, role_id=role_id)
    assert row is not None
    return _row_to_role(row)


async def get_role_permissions(db: AsyncSession, *, company_id: UUID, role_id: UUID) -> list[str]:
    role = await repository.get_role(db, company_id=company_id, role_id=role_id)
    if role is None:
        raise NotFoundError("El rol no existe en esta empresa.")
    return await repository.role_permission_codes(db, role_id=role_id)


async def update_role_permissions(
    db: AsyncSession,
    *,
    company_id: UUID,
    role_id: UUID,
    codes: list[str],
    acting_user_id: UUID,
    acting_role_id: UUID,
) -> list[str]:
    # F3-07: quitarle `identity.manage_roles` a un rol es el tercer camino
    # para quedarse sin admins; comparte el candado con los otros dos.
    await repository.lock_admin_safeguard(db, company_id=company_id)
    role = await repository.get_role(db, company_id=company_id, role_id=role_id)
    if role is None:
        raise NotFoundError("El rol no existe en esta empresa.")

    catalog = {row._mapping["code"] for row in await repository.list_permissions(db)}
    unknown = set(codes) - catalog
    if unknown:
        raise AppError(
            "Hay códigos de permiso que no existen en el catálogo.",
            details={"unknown_codes": sorted(unknown)},
        )

    before_codes = await repository.role_permission_codes(db, role_id=role_id)
    # Solo se exige para lo que se AGREGA: un permiso que el rol ya tenía no lo
    # está otorgando quien edita, y quitar nunca amplía nada (F3-02).
    _ensure_within_actor(
        set(codes) - set(before_codes),
        await _actor_permission_codes(db, acting_role_id),
        message="No puedes darle a un rol un permiso que tú no tienes.",
    )
    if _ADMIN_PERMISSION in before_codes and _ADMIN_PERMISSION not in codes:
        remaining = await repository.count_other_active_admins(
            db, company_id=company_id, excluding_role_id=role_id
        )
        if remaining == 0:
            raise ConflictError(
                "No se puede quitar 'identity.manage_roles' del último rol con administradores.",
                code="LAST_ADMIN_SAFEGUARD",
            )

    await repository.set_role_permissions(db, role_id=role_id, codes=codes)
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="update_role_permissions",
        entity_type="role",
        entity_id=role_id,
        before={"permission_codes": sorted(before_codes)},
        after={"permission_codes": sorted(codes)},
    )
    return await repository.role_permission_codes(db, role_id=role_id)


async def list_permissions(db: AsyncSession) -> list[PermissionOut]:
    rows = await repository.list_permissions(db)
    return [
        PermissionOut(
            id=r._mapping["id"],
            code=r._mapping["code"],
            module=r._mapping["module"],
            action=r._mapping["action"],
            is_special=r._mapping["is_special"],
            description=r._mapping["description"],
        )
        for r in rows
    ]


async def get_me(db: AsyncSession, *, user: CurrentUser) -> MeOut:
    """El front no puede saber qué puede hacer el usuario logueado sin esto:
    `GET /identity/roles/{id}/permissions` exige `identity.manage_roles`, que
    un Asesor no tiene. Devuelve exactamente el mismo set de permisos
    (mismo cache TTL 60s) que `require_permission` va a aceptar o rechazar.
    """
    role_row = await repository.get_role(db, company_id=user.company_id, role_id=user.role_id)
    if role_row is None:
        raise NotFoundError("El rol del usuario no existe en esta empresa.")

    company_row = await platform_repo.get_company_profile(db, company_id=user.company_id)
    if company_row is None:
        raise NotFoundError("La empresa no existe.")

    subscription_row = await platform_repo.get_active_subscription_with_plan(
        db, company_id=user.company_id
    )
    if subscription_row is None:
        raise NotFoundError("La empresa no tiene una suscripción activa.")

    permissions = await get_cached_role_permissions(db, user.role_id)

    # El nombre y la foto se leen de la BD, no de `user` (CurrentUser): ese
    # viene de un cache de 30s, así que justo después de `PATCH /me` el
    # usuario vería todavía su nombre viejo. La empresa y el rol sí pueden
    # venir del cache — no los cambia el propio usuario.
    user_row = await repository.get_user(db, company_id=user.company_id, user_id=user.id)
    um = user_row._mapping if user_row is not None else None

    cm = company_row._mapping
    sm = subscription_row._mapping
    company_settings = cm["settings"] or {}
    documents = company_settings.get("documents") or {}
    return MeOut(
        user=MeUserOut(
            id=user.id,
            full_name=um["full_name"] if um else user.full_name,
            email=um["email"] if um else user.email,
            photo_url=um["photo_url"] if um else None,
        ),
        company=MeCompanyOut(
            id=cm["id"],
            name=cm["name"],
            timezone=company_settings.get("timezone", "America/Bogota"),
            logo_url=cm["logo_url"],
            signature_url=cm["signature_url"],
            legal_name=cm["legal_name"],
            tax_id=cm["tax_id"],
            address=cm["address"],
            contact_phone=cm["contact_phone"],
            documents=MeDocumentsOut(
                header_note=documents.get("header_note"),
                footer_note=documents.get("footer_note"),
                legal_notice=documents.get("legal_notice"),
            ),
        ),
        role=MeRoleOut(id=role_row._mapping["id"], name=role_row._mapping["name"]),
        permissions=permissions,
        subscription=MeSubscriptionOut(status=sm["status"], expires_at=sm["expires_at"]),
        plan=MePlanOut(code=sm["plan_code"], name=sm["plan_name"]),
    )


async def generate_recovery_link(
    db: AsyncSession,
    *,
    company_id: UUID,
    user_id: UUID,
    acting_user_id: UUID,
    acting_role_id: UUID,
) -> RecoveryLinkOut:
    """Enlace para que un usuario vuelva a poner su contraseña, sin correo.

    Cierra el único hueco funcional que dejaba no tener correo propio: invitar
    ya se podía hacer por enlace, pero recuperar la contraseña dependía del
    envío, y con el SMTP incluido de Supabase eso significa que un olvido podía
    dejar a alguien afuera sin que nadie pudiera ayudarlo.
    """
    user = await repository.get_user(db, company_id=company_id, user_id=user_id)
    if user is None:
        raise NotFoundError("El usuario no existe en esta empresa.")

    # Un usuario inactivo no debe poder volver a entrar: darle el enlace sería
    # deshacer la desactivación por la puerta de atrás, sin quedar registrado
    # como una reactivación.
    if user._mapping["status"] == "inactive":
        raise ConflictError(
            "Este usuario está inactivo. Reactívalo primero si quiere volver a entrar."
        )

    # El enlace deja entrar COMO esa persona, con todos sus permisos: generarlo
    # para alguien con permisos que el actor no tiene sería entregarlos (F3-02).
    await _ensure_role_within_actor(
        db,
        role_id=user._mapping["role_id"],
        actor_role_id=acting_role_id,
        message=(
            "No puedes generar un enlace de acceso para alguien que tiene permisos "
            "que tú no tienes."
        ),
    )

    email = user._mapping["email"]
    await _ensure_invitation_quota(db, company_id=company_id)
    link = await auth_admin.generate_recovery_link(email)

    # Se audita SIEMPRE: el enlace es una credencial, y el registro de quién lo
    # generó y para quién es lo único que queda si después hay que explicar un
    # acceso. El enlace en sí NO se guarda — el audit_log es consultable y
    # dejaría la credencial al alcance de cualquiera con `audit.view`.
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="generate_recovery_link",
        entity_type="app_user",
        entity_id=user_id,
        after={"email": email},
    )
    return RecoveryLinkOut(user_id=user_id, email=email, recovery_link=link)


async def update_me(db: AsyncSession, *, user: CurrentUser, body: MeUpdateIn) -> MeOut:
    """El usuario edita SU PROPIO perfil: nombre y foto, nada más.

    Sin permiso de identidad — editarse a uno mismo no es gestionar usuarios.
    Justamente por eso el schema (`MeUpdateIn`) no admite `role_id` ni
    `status`: si los admitiera, cualquiera se ascendería a admin desde su
    perfil, rodeando `identity.manage_users` por otra URL.

    No audita: cambiarse el nombre propio no es una acción sensible de las que
    lista CLAUDE.md (descuentos, remates, anulaciones, cambios de rol). El
    `updated_at` de la fila queda como rastro.
    """
    fields = body.model_dump(exclude_unset=True)
    if fields:
        await repository.update_me(db, company_id=user.company_id, user_id=user.id, fields=fields)
        # El cache de `CurrentUser` (30s) todavía tiene el nombre viejo; el
        # `get_me` de abajo lee la fila de la BD, así que la respuesta ya sale
        # con el valor nuevo aunque el cache no haya expirado.
    return await get_me(db, user=user)
