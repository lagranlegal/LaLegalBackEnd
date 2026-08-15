"""Exporta el esquema OpenAPI a un archivo, sin levantar un servidor.

Uso: python scripts/export_openapi.py [ruta_salida]  (default: openapi.json)
"""

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    output.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False))
    print(f"OpenAPI exportado a {output}")


if __name__ == "__main__":
    main()
