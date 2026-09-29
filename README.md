# Prendo — backend

API de **Prendo**, el SaaS multi-tenant para compraventas colombianas (empeño + tienda): FastAPI sobre Supabase
(Postgres con RLS, Auth, Storage), desplegada en Fly.io. El front vive en el repo `frontend-starter`.

**Toda la documentación empieza en [`docs/README.md`](docs/README.md)** (qué es, piezas, mapa de documentos) y el
estado del día en [`docs/ESTADO.md`](docs/ESTADO.md). Las reglas para escribir código: [`CLAUDE.md`](CLAUDE.md).

```bash
supabase start && supabase db reset             # Postgres local con migraciones + seed (Docker)
.venv/bin/python -m pytest -q tests/unit tests/rls
ruff check . && ruff format --check . && mypy app
uvicorn app.main:app --reload
```

Ramas: `dev` es la rama por defecto y la de todo el trabajo; `main` será la de producción cuando exista. Deploy de
dev: `./scripts/deploy_dev.sh` ([`docs/OPERACION.md`](docs/OPERACION.md) §2).
