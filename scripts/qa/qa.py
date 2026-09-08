"""Arsenal de QA — cliente HTTP que asevera por `code`, nunca por status solo.

Regla del proyecto: "un codigo de error es un contrato entre dos capas".
Todo assert de error va contra el campo `code` del envelope {code,message,details}.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

# scripts/qa/qa.py → la raíz del workspace está tres niveles arriba.
ROOT = pathlib.Path(__file__).resolve().parents[3]
# Los artefactos de una corrida (tokens, ids sembrados, resultados) NO se
# versionan: son de un laboratorio concreto y caducan con él.
SCRATCH = pathlib.Path(__file__).parent / "_run"
SCRATCH.mkdir(exist_ok=True)

# Contraseña de los usuarios de prueba de la empresa espejo (ambiente dev,
# usuarios desechables). Se puede sobreescribir con QA_PASSWORD.
TEST_PASSWORD = os.environ.get("QA_PASSWORD", "QaLab2026!")


def _dotenv(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


BE = _dotenv(ROOT / "backend-starter" / ".env")
FE = _dotenv(ROOT / "frontend-starter" / ".env")

SUPABASE_URL = BE["SUPABASE_URL"].rstrip("/")
SERVICE_ROLE = BE["SUPABASE_SERVICE_ROLE_KEY"]
ANON = FE["VITE_SUPABASE_ANON_KEY"]
API = FE["VITE_API_URL"].rstrip("/") + "/api/v1"

TIMEOUT = httpx.Timeout(60.0)


# ---------------------------------------------------------------- auth ------
def login(email: str, password: str) -> dict[str, Any]:
    """Login contra Supabase Auth (el backend no tiene login propio)."""
    r = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def admin_headers() -> dict[str, str]:
    return {
        "apikey": SERVICE_ROLE,
        "Authorization": f"Bearer {SERVICE_ROLE}",
        "Content-Type": "application/json",
    }


def decode_jwt(token: str) -> dict[str, Any]:
    import base64

    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


# ------------------------------------------------------------- cliente ------
@dataclass
class Result:
    method: str
    path: str
    status: int
    code: str | None
    body: Any
    elapsed: float

    def __repr__(self) -> str:
        c = f" code={self.code}" if self.code else ""
        return f"<{self.method} {self.path} -> {self.status}{c} ({self.elapsed:.2f}s)>"

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass
class Client:
    """Cliente del backend para un actor concreto (un rol)."""

    label: str
    token: str
    calls: list[Result] = field(default_factory=list)

    def request(
        self, method: str, path: str, *, idem: bool | str = False, **kw: Any
    ) -> Result:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        if idem:
            headers["Idempotency-Key"] = idem if isinstance(idem, str) else str(uuid.uuid4())
        t0 = time.time()
        r = httpx.request(method, f"{API}{path}", headers=headers, timeout=TIMEOUT, **kw)
        elapsed = time.time() - t0
        try:
            body = r.json()
        except Exception:
            body = r.text
        code = body.get("code") if isinstance(body, dict) else None
        res = Result(method, path, r.status_code, code, body, elapsed)
        self.calls.append(res)
        return res

    def get(self, path: str, **kw: Any) -> Result:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Result:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> Result:
        return self.request("PATCH", path, **kw)

    def put(self, path: str, **kw: Any) -> Result:
        return self.request("PUT", path, **kw)

    def delete(self, path: str, **kw: Any) -> Result:
        return self.request("DELETE", path, **kw)


def client_for(email: str, password: str, label: str) -> Client:
    return Client(label=label, token=login(email, password)["access_token"])


# ------------------------------------------------------------ registro ------
FINDINGS: list[dict[str, Any]] = []


def check(name: str, condition: bool, detail: str = "", severity: str = "media") -> bool:
    """Registra una comprobacion. Devuelve el resultado para encadenar."""
    status = "PASA" if condition else "FALLA"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        FINDINGS.append({"name": name, "detail": detail, "severity": severity})
    return condition


def save(name: str, data: Any) -> None:
    p = SCRATCH / f"{name}.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    print(f"  → guardado en {p.name}")


def load(name: str) -> Any:
    return json.loads((SCRATCH / f"{name}.json").read_text())
