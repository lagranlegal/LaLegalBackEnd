import logging
from typing import Any, NamedTuple

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Error de negocio con respuesta uniforme {code, message, details}."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"
    #: Cabeceras HTTP extra de la respuesta de error. Hoy solo `Retry-After`
    #: del 429 (`app/common/rate_limit.py`).
    headers: dict[str, str] | None = None

    def __init__(
        self, message: str, details: dict[str, Any] | None = None, code: str | None = None
    ) -> None:
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        super().__init__(message)


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "PERMISSION_DENIED"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class SubscriptionExpiredError(AppError):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "SUBSCRIPTION_EXPIRED"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class CashSessionNotOpenError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CASH_SESSION_NOT_OPEN"


class MultipleRegistersNotSupportedError(AppError):
    """La empresa tiene más de una caja registradora activa y multi-caja
    todavía no está implementado.

    **Hoy no se puede llegar acá por la API**: ningún endpoint crea una
    `cash_register` — solo `platform.create_company_defaults` al dar de alta
    la empresa, y crea exactamente una. Este error existe para el caso de que
    alguien inserte la segunda a mano, o para el día que se empiece a
    construir multi-caja y algo quede a medias.

    La alternativa era seguir tomando "la más antigua" en silencio. Eso no es
    un valor por defecto razonable: significa que la mitad de las operaciones
    de dinero de la empresa se registrarían contra una caja al azar y **nadie
    se enteraría**. Fallar fuerte convierte un descuadre inexplicable en un
    mensaje que dice qué pasa.

    Ver `docs/SUCURSALES.md` §5, Acción B.
    """

    status_code = status.HTTP_409_CONFLICT
    code = "MULTIPLE_REGISTERS_NOT_SUPPORTED"


class NoOpenCashSessionError(NotFoundError):
    """ "No hay caja abierta" CONSULTADO, no intentado.

    Es un 404 —se preguntó por la sesión en curso y no hay ninguna— pero lleva
    el código de dominio `CASH_SESSION_NOT_OPEN`, no el `NOT_FOUND` genérico.

    BUG REAL (03/09/2026): `GET /cashbox/sessions/current` devolvía
    `NOT_FOUND`, y el front buscaba exactamente `CASH_SESSION_NOT_OPEN` para
    traducirlo a "caja cerrada". Como nunca coincidía, la franja global caía
    en su rama de error y mostraba **"No se pudo consultar el estado de la
    caja"** — un fallo del sistema— en vez de "Caja cerrada — no se pueden
    registrar operaciones de dinero" con el botón para abrirla. Toda la rama
    de caja cerrada del banner era código muerto.

    Efecto en la vida real: una empresa estuvo once días sin poder crear un
    solo contrato (el desembolso en efectivo exige sesión abierta) porque
    nadie supo nunca que lo que faltaba era abrir la caja. La app decía que
    no podía averiguarlo.

    Se distingue a propósito del otro 404 de este endpoint —"la empresa no
    tiene una caja activa configurada"—, que sí es un problema de
    configuración y debe seguir viéndose como falla.
    """

    code = "CASH_SESSION_NOT_OPEN"


class InvalidDateRangeError(AppError):
    """Un reporte por período con `from_date` posterior a `to_date`, o más
    largo que el tope del endpoint (F7-14). 422 con código propio y no el 400
    genérico: el front tiene que poder decir «el rango está al revés» en vez
    de «algo falló», y un rango invertido que responde 200 con ceros afirma
    un período vacío que no existe."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "INVALID_DATE_RANGE"


class SaleBelowCostRequiresPermissionError(PermissionDeniedError):
    """Una línea de venta con `unit_price` por debajo del COSTO de su lote,
    sin `sales.apply_discount` (decisión del dueño, auditoría fase 7). Es un
    403 propio y no `PERMISSION_DENIED` a secas porque el front tiene que
    poder decir «esta venta pierde plata» en vez de «no tiene permiso»."""

    code = "SALE_BELOW_COST_REQUIRES_PERMISSION"


class PaymentPartialInterestRejectedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "PAYMENT_PARTIAL_INTEREST_REJECTED"


class PaymentMinimumInterestRequiredError(AppError):
    """Saldar un contrato que no ha causado ningún mes de interés exige
    cubrir uno (F4-11)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "PAYMENT_MINIMUM_INTEREST_REQUIRED"


class ContractAppraisalRequiredError(AppError):
    """Contrato sin avalúo en una categoría con `max_ltv_pct` (F4-05)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "CONTRACT_APPRAISAL_REQUIRED"


class ImportDatesMisalignedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "IMPORT_DATES_MISALIGNED"


class ImportCapitalExceedsPrincipalError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "IMPORT_CAPITAL_EXCEEDS_PRINCIPAL"


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "details": details},
        headers=headers,
    )


class _UniqueCode(NamedTuple):
    code: str
    message: str


#: Índices/constraints UNIQUE que tienen un nombre de negocio propio. La
#: clave es el nombre en Postgres; se lee de la excepción de asyncpg, no se
#: busca en el texto del mensaje. `code=` con nombre a propósito: así lo ve
#: `tests/unit/test_error_catalog.py` y exige su fila en API_GUIDE §15.
_UNIQUE_CODES: dict[str, _UniqueCode] = {
    "role_company_id_name_key": _UniqueCode(
        code="ROLE_NAME_TAKEN", message="Ya existe un rol con ese nombre."
    ),
    "account_company_id_name_key": _UniqueCode(
        code="ACCOUNT_NAME_TAKEN", message="Ya existe una cuenta con ese nombre."
    ),
    "expense_category_company_id_name_key": _UniqueCode(
        code="EXPENSE_CATEGORY_NAME_TAKEN",
        message="Ya existe una categoría de gasto con ese nombre.",
    ),
    "category_company_id_parent_id_name_key": _UniqueCode(
        code="CATEGORY_NAME_TAKEN",
        message="Ya existe una categoría con ese nombre en ese nivel.",
    ),
}

_UNIQUE_VIOLATION = "23505"
_NOT_NULL_VIOLATION = "23502"
_CHECK_VIOLATION = "23514"


def _pg_error(exc: Exception) -> tuple[str | None, Any]:
    """`(sqlstate, excepción de asyncpg)` detrás de la de SQLAlchemy. El
    adaptador de asyncpg copia el `sqlstate` en `exc.orig`, y la original —con
    `constraint_name`, `column_name`— queda como su `__cause__`."""
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None), getattr(orig, "__cause__", None)


def _db_validation_error(message: str, **ctx: Any) -> JSONResponse:
    """Un valor que la BASE rechazó por inválido (CHECK, NOT NULL, fuera de
    rango) es un error de validación como cualquier otro: 422 con el mismo
    `code` y la misma forma que los de Pydantic, así el front no necesita
    un segundo camino."""
    error: dict[str, Any] = {
        "loc": ["body", ctx["column"]] if ctx.get("column") else ["body"],
        "msg": message,
        "type": ctx.pop("type"),
    }
    if ctx:
        error["ctx"] = ctx
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "VALIDATION_ERROR",
        "Los datos enviados no son válidos.",
        {"errors": [error]},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        """Traduce los conflictos que la BASE detecta a errores de negocio.

        Dos operaciones simultáneas sobre lo mismo llegan hasta acá: las
        validaciones del servicio comprueban «hay stock» / «no existe esa clave»
        antes de escribir, y bajo concurrencia las dos pasan esa comprobación
        porque ninguna ha escrito todavía. Quien salva la integridad es la base
        —el `CHECK` y el `UNIQUE`— y eso está bien: es el diseño del proyecto.

        Lo que estaba mal era la respuesta. Sin este handler, quien perdía la
        carrera recibía un `500` en texto plano, sin el envelope `{code, message,
        details}` y sin nada que el front pudiera mapear: el cajero veía «algo
        salió mal» sin saber si la venta se hizo. Medido en la Fase 10 de la
        auditoría: de cinco ventas simultáneas de la última unidad, cuatro
        respondían 500.

        Se traduce solo lo que sabemos nombrar; cualquier otra violación sigue
        subiendo como 500, porque un error que no entendemos no debe disfrazarse
        de error de negocio.
        """
        detalle = str(getattr(exc, "orig", exc))

        if "idempotency_key" in detalle:
            # El reintento llegó mientras la primera petición seguía en vuelo,
            # que es justo el caso para el que existe la `Idempotency-Key`. La
            # original va a terminar bien: lo correcto es decirlo, no fallar.
            return _error_response(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_IN_PROGRESS",
                "Esta misma operación ya se está registrando. No la repitas: "
                "consulta el resultado en unos segundos.",
                {},
            )

        if "uq_session_open" in detalle:
            # Red de seguridad: `open_session` ya bloquea la registradora
            # (F5-04), así que una apertura simultánea debería ver la sesión y
            # responder esto mismo desde el servicio. Si algún camino llega
            # al índice, el cajero ve "ya está abierta" y no un 500.
            return _error_response(
                status.HTTP_409_CONFLICT,
                "CASH_SESSION_ALREADY_OPEN",
                "Ya hay una sesión de caja abierta.",
                {},
            )

        if "quantity_check" in detalle:
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "BAD_REQUEST",
                "No hay suficiente cantidad disponible.",
                {},
            )

        # Lo que sigue lo traduce por SQLSTATE y nombre de constraint (F5-04,
        # F3-04, F3-05; auditoría 27/09/2026). La validación de primera línea
        # es Pydantic (`PositiveMoney`, `Quantity`, `Reason`, rangos); esto es
        # la red para lo que solo la base puede ver —un nombre repetido— o
        # para un campo que se escape de esa validación. En todos los casos
        # el valor lo mandó el cliente, así que el error es suyo: 409 o 422
        # con envelope, nunca un 500 en texto plano. Se registra igual, para
        # que un campo sin validar en el schema no pase inadvertido.
        sqlstate, pg = _pg_error(exc)
        constraint = getattr(pg, "constraint_name", None)
        if sqlstate == _UNIQUE_VIOLATION:
            code, message = _UNIQUE_CODES.get(
                constraint or "",
                _UniqueCode(code="CONFLICT", message="Ya existe un registro con esos datos."),
            )
            return _error_response(
                status.HTTP_409_CONFLICT, code, message, {"constraint": constraint}
            )
        if sqlstate == _NOT_NULL_VIOLATION:
            column = getattr(pg, "column_name", None)
            logger.warning("NOT NULL violado por el cuerpo de la petición: %s", column)
            return _db_validation_error(
                "Este campo no puede quedar vacío.", type="not_null", column=column
            )
        if sqlstate == _CHECK_VIOLATION:
            logger.warning("CHECK violado por el cuerpo de la petición: %s", constraint)
            return _db_validation_error(
                "Un valor está fuera de lo permitido.", type="check", constraint=constraint
            )

        raise exc

    @app.exception_handler(DBAPIError)
    async def handle_data_error(_request: Request, exc: DBAPIError) -> JSONResponse:
        """Clase 22 de SQLSTATE ("data exception"): un valor que no cabe en la
        columna —`numeric(5,2)` con 1000, F3-06— o que no se puede convertir.
        Mismo criterio que arriba: 422, no 500. El adaptador de asyncpg no la
        sube como `DataError` sino como `DBAPIError`, así que se mira el
        `sqlstate`; cualquier otra clase sigue subiendo como 500."""
        sqlstate, _pg = _pg_error(exc)
        if not (sqlstate or "").startswith("22"):
            raise exc
        logger.warning("Valor rechazado por la base: sqlstate=%s", sqlstate)
        return _db_validation_error(
            "Un valor no cabe en el formato permitido.", type="data", sqlstate=sqlstate
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            "Los datos enviados no son válidos.",
            {"errors": jsonable_encoder(exc.errors())},
        )
