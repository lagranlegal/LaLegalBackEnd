from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.common.cors import build_cors_config
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.modules.accounts.router import router as accounts_router
from app.modules.audit.router import router as audit_router
from app.modules.cashbox.router import router as cashbox_router
from app.modules.catalogs.router import router as catalogs_router
from app.modules.company.router import router as company_router
from app.modules.contracts.router import router as contracts_router
from app.modules.customers.router import router as customers_router
from app.modules.identity.router import router as identity_router
from app.modules.identity.router import router_me as me_router
from app.modules.inventory.router import router as inventory_router
from app.modules.platform.router import router as platform_router
from app.modules.reports.router import router as reports_router
from app.modules.sales.router import router as sales_router


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    origins, origin_regex = build_cors_config(
        cors_allow_origins=settings.cors_allow_origins, environment=settings.environment
    )

    app = FastAPI(title="Compraventa Backend", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=origin_regex,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(platform_router)
    app.include_router(identity_router)
    app.include_router(me_router)
    app.include_router(accounts_router)
    app.include_router(company_router)
    app.include_router(customers_router)
    app.include_router(catalogs_router)
    app.include_router(contracts_router)
    app.include_router(cashbox_router)
    app.include_router(inventory_router)
    app.include_router(sales_router)
    app.include_router(audit_router)
    app.include_router(reports_router)

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
