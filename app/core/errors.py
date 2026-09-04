from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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
