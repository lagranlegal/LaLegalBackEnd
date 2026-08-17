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
