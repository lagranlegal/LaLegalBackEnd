FROM python:3.12-slim AS base

WORKDIR /app

# Certificados TLS del sistema — necesarios para hablar HTTPS con Supabase
# (JWKS, Auth Admin API) desde el contenedor.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
