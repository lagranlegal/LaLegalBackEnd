from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class AppError(Exception):
    """Error de negocio con respuesta uniforme {code, message, details}."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

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


class PaymentPartialInterestRejectedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "PAYMENT_PARTIAL_INTEREST_REJECTED"


class ImportDatesMisalignedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "IMPORT_DATES_MISALIGNED"


class ImportCapitalExceedsPrincipalError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "IMPORT_CAPITAL_EXCEEDS_PRINCIPAL"


def _error_response(
    status_code: int, code: str, message: str, details: dict[str, Any]
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "details": details},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

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

        if "quantity_check" in detalle:
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "BAD_REQUEST",
                "No hay suficiente cantidad disponible.",
                {},
            )

        raise exc

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
