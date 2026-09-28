from typing import Any

from pydantic import field_validator


def _rechazar_null(cls: Any, value: Any) -> Any:
    if value is None:
        raise ValueError("No puede ser null. Para no cambiarlo, omite el campo.")
    return value


def no_null(*fields: str) -> Any:
    """Validador para un PATCH parcial: el campo se puede OMITIR, pero no
    mandar como `null` si su columna es NOT NULL (F3-04, auditoría
    27/09/2026).

    En estos esquemas `None` es el default que significa "no vino" y el
    servicio escribe solo lo que vino (`exclude_unset`). Un `null` explícito
    viajaba entonces hasta el UPDATE y lo rechazaba la base —un 500— en vez
    de responder 422 con el campo en `loc`. Pydantic solo corre el validador
    sobre lo que el cliente mandó, así que omitir el campo sigue permitido.

    Uso: `_no_null = no_null("name", "phone")` dentro del modelo.
    """
    return field_validator(*fields)(_rechazar_null)
