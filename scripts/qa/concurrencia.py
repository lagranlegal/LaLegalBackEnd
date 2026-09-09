"""Dos cajeros haciendo lo mismo al mismo tiempo.

Es lo único que no se descubre probando de a uno: el sistema puede estar
perfecto en secuencia y vender dos veces la última unidad si dos personas
confirman a la vez. En una compraventa con dos mostradores eso pasa.
"""

import asyncio
import uuid

import httpx
import qa

S = qa.load("seed")
SES = qa.load("sessions")


async def disparar(n, hacer):
    """Lanza `n` peticiones a la vez de verdad (mismo instante, no en fila)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as c:
        listo = asyncio.Event()

        async def una(i):
            await listo.wait()  # todas esperan y salen juntas
            return await hacer(c, i)

        tareas = [asyncio.create_task(una(i)) for i in range(n)]
        await asyncio.sleep(0.4)
        listo.set()
        return await asyncio.gather(*tareas, return_exceptions=True)


def resumen(rs):
    out = []
    for r in rs:
        if isinstance(r, Exception):
            out.append(f"EXC {type(r).__name__}")
            continue
        try:
            b = r.json()
        except Exception:
            b = {}
        code = b.get("code") if isinstance(b, dict) else None
        num = b.get("number") if isinstance(b, dict) else None
        out.append(f"{r.status_code}{' ' + code if code else ''}{' #' + str(num) if num else ''}")
    return out


async def main():
    tok = SES["Admin"]["token"]
    H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    item = qa.load("item_concurrencia")

    print("=== 1. Cinco ventas simultáneas de la ÚLTIMA unidad ===")
    print("    (claves de idempotencia DISTINTAS: son cinco intentos legítimos, no un reintento)")

    async def vender(c, i):
        return await c.post(
            f"{qa.API}/sales",
            headers={**H, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "payment_method": "cash",
                "lines": [{"item_id": item["id"], "quantity": 1, "unit_price": "250000"}],
            },
        )

    rs = await disparar(5, vender)
    print("   ", resumen(rs))
    ok = sum(1 for r in rs if not isinstance(r, Exception) and r.status_code == 201)
    print(f"    ventas creadas: {ok}  ← debe ser exactamente 1")

    a = qa.Client("Admin", tok)
    est = a.get(f"/inventory/items/{item['id']}").body
    print(f"    stock final: {est['quantity']} · estado {est['status']}  ← debe ser 0 y 'sold'")

    print("\n=== 2. Misma Idempotency-Key, cinco veces a la vez ===")
    print("    (un reintento de red real: cinco requests idénticas en el mismo instante)")
    item2 = a.post(
        "/inventory/entries",
        json={
            "origin_type": "initial_stock",
            "lines": [
                {
                    "name": "Pieza para idempotencia",
                    "cat1_id": S["categories"]["Joyería"],
                    "cat2_id": S["categories"]["Oro"],
                    "cat3_id": S["categories"]["Anillo"],
                    "unit_cost": "50000",
                    "quantity": 5,
                    "sale_price": "90000",
                }
            ],
        },
        idem=True,
    ).body["items"][0]
    key = str(uuid.uuid4())

    async def vender_misma_key(c, i):
        return await c.post(
            f"{qa.API}/sales",
            headers={**H, "Idempotency-Key": key},
            json={
                "payment_method": "cash",
                "lines": [{"item_id": item2["id"], "quantity": 1, "unit_price": "90000"}],
            },
        )

    rs = await disparar(5, vender_misma_key)
    print("   ", resumen(rs))
    nums = {
        r.json().get("number") for r in rs if not isinstance(r, Exception) and r.status_code < 300
    }
    print(f"    números de venta distintos: {nums}  ← debe ser uno solo")
    st2 = a.get("/inventory/items/" + item2["id"]).body["quantity"]
    print(f"    stock: {st2}  ← debe bajar 1, no 5")

    print("\n=== 3. Cinco aperturas de caja simultáneas (con la caja YA abierta) ===")

    async def abrir(c, i):
        return await c.post(
            f"{qa.API}/cashbox/sessions/open", headers=H, json={"opening_balance": "1000"}
        )

    print("   ", resumen(await disparar(5, abrir)))

    print("\n=== 4. Cinco abonos simultáneos al mismo contrato ===")
    contratos = [x for x in a.get("/contracts", params={"status": "active"}).body["items"]]
    if contratos:
        cid = contratos[0]["id"]
        o = a.get(f"/contracts/{cid}/payment-options").body
        print(f"    contrato #{contratos[0]['number']} · debe {o['months_owed']} mes(es)")
        if o["months_owed"] > 0:

            async def abonar(c, i):
                return await c.post(
                    f"{qa.API}/contracts/{cid}/payments",
                    headers={**H, "Idempotency-Key": str(uuid.uuid4())},
                    json={"months_covered": 1, "payment_method": "cash"},
                )

            rs = await disparar(5, abonar)
            print("   ", resumen(rs))
            c2 = a.get(f"/contracts/{cid}").body
            print(f"    interés pagado hasta: {c2['interest_paid_until']}")
            debe = o["months_owed"]
            print(f"    ← con {debe} mes(es) adeudado(s), no puede aceptar 5 abonos de 1 mes")
        else:
            print("    (el contrato está al día; no aplica)")


asyncio.run(main())
