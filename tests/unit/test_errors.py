from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import PermissionDeniedError, register_exception_handlers


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise PermissionDeniedError("Falta el permiso.", details={"permission": "x.y"})

    return app


def test_app_error_has_uniform_shape() -> None:
    client = TestClient(_build_app())
    response = client.get("/boom")

    assert response.status_code == 403
    assert response.json() == {
        "code": "PERMISSION_DENIED",
        "message": "Falta el permiso.",
        "details": {"permission": "x.y"},
    }


def test_validation_error_has_uniform_shape() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/echo")
    async def echo(value: int) -> dict[str, int]:
        return {"value": value}

    client = TestClient(app)
    response = client.get("/echo", params={"value": "not-an-int"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "errors" in body["details"]
