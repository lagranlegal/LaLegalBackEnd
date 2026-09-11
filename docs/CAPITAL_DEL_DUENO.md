# CAPITAL_DEL_DUENO.md — Aportes y retiros del dueño (spec)

> **Estado: IMPLEMENTADO** (migración `00054`, 11/09/2026). Pedido por Mateo probando con el cliente, en dos preguntas que resultaron ser la misma:
>
> - *"Estamos bajos de capital para prestar; el dueño le va a meter x cantidad al negocio. ¿Cómo está cubierto contablemente?"*
> - *"El dueño quiere retirar x por utilidad. ¿Cómo se le da salida de forma profesional?"*
>
> **Principio de diseño:** ni un aporte es un ingreso, ni un retiro es un gasto. Los dos mueven el **patrimonio**, no el resultado del período. Todo lo demás sale de ahí.

---

## 1. Qué pasaba antes, y por qué las tres salidas estaban mal

El dueño que metía plata tenía tres caminos y ninguno servía:

| Cómo se registraba | Por qué está mal |
|---|---|
| Como `adjustment` de arqueo | Un ajuste significa *"el sistema no cuadra con la realidad y lo estoy corrigiendo"*. Acá cuadra perfecto: hubo un hecho real, con fecha, monto y responsable |
| Como traslado | Solo sirve si la plata **ya está** en una cuenta de la empresa. El bolsillo del dueño no lo es |
| Sin registrar | La plata aparece en el cajón sin documento. Es exactamente el *"número inventado"* que [`CAJA_TRAZABILIDAD.md`](CAJA_TRAZABILIDAD.md) y la migración `00048` existen para eliminar |

Y el retiro registrado como **gasto** falsea la utilidad del período por todo el monto retirado. Es el mismo error que este proyecto ya pagó tres veces —*"prestar no es un gasto, cobrar no es una ganancia"*— y que `00032` documentó para las consignaciones.

## 2. Cómo lo resuelve un sistema contable, y qué se tomó de eso

En partida doble un aporte es `Débito Caja / Crédito Patrimonio`; un retiro, `Débito Patrimonio / Crédito Caja`. En QuickBooks o Xero son las cuentas *Owner's Contribution* y *Owner's Draw*.

Lo esencial de todo eso cabe en una frase: **ninguno de los dos pasa por el estado de resultados.**

**Y esta app no necesita construir partida doble para cumplirlo.** `get_income_statement` lee **documentos** (`sale`, `contract_payment`, `expense`), nunca `cash_movement`. Un documento nuevo que no sea ninguno de esos tres queda fuera del resultado **por construcción** — sin una sola línea de exclusión que alguien pueda olvidar.

Es la mejor señal de que el diseño va por donde corresponde: el modelo ya protegía esto antes de que el caso existiera.

## 3. Un solo documento para los dos casos

Aporte y retiro son el mismo concepto en dos sentidos, igual que un traslado es una salida y una entrada. Partirlo en dos tablas duplicaría el número, la idempotencia, el RLS, la auditoría y la pantalla para expresar una diferencia que cabe en una columna.

```sql
create table public.capital_movement (
  direction  capital_direction not null,        -- contribution | withdrawal
  kind       capital_withdrawal_kind,           -- profit | capital_return (solo retiros)
  account_id uuid not null,
  amount     numeric(14,2) not null,
  movement_date date not null,
  notes      text,                              -- OBLIGATORIO en el retiro
  ...
);
```

**Por qué una tabla y no solo un `cash_movement` con otro concepto:** `CLAUDE.md` regla 4 — los movimientos de caja los generan los servicios **desde documentos**. El documento guarda la fecha real, el motivo, quién lo hizo y la clave de idempotencia. Es el mismo argumento textual de `00032`.

**Conceptos propios** (`owner_contribution` / `owner_withdrawal`) y no `adjustment`: mezclarlos haría imposible separarlos después.

### `kind`: una columna, un default, cero UI el día uno

Contablemente **no son lo mismo** retirar utilidad (reduce las ganancias acumuladas) y devolver capital (reduce el aporte). Para el dueño de una compraventa la distinción no existe hasta que llega la declaración.

Así que el campo existe, con `profit` por defecto, y **ninguna pantalla lo muestra**. Es el mismo patrón de `extension_interest_policy` (`00051`), que quedó puesto sin exponerse y resultó ser exactamente lo que hizo falta tres días después.

## 4. Lo que el dueño ve antes de retirar — la parte que vale

`GET /capital/position` contesta la pregunta que un dueño de compraventa **no puede responder de memoria**: en este negocio la mayor parte del capital **no está en el cajón**.

```
Disponible      $ 4.200.000   ← cajón + bóveda + bancos
Prestado        $32.500.000   ← capital de los contratos vivos
Inventario      $14.240.000   ← AL COSTO, nunca al precio de venta
                ───────────
Capital total   $50.940.000

Utilidad del período   $ 8.400.000
Retiros ya hechos      $ 3.000.000
                       ───────────
Sin repartir           $ 5.400.000
```

**Retirar "lo que hay en caja" no es retirar utilidad: es descapitalizar.** Ese es el aviso entero.

Detalles que importan:

- **El inventario va al costo.** Contar la utilidad antes de venderla es el error clásico, y acá alimentaría directamente una decisión de sacar dinero.
- **Las cuentas por cobrar quedan fuera** de lo disponible: *"una cuenta por cobrar no es plata"*. Sumarlas haría creer que hay más de lo que hay, justo en la pantalla donde eso más duele.
- **`distributable` puede salir negativo**, y es a propósito: significa que lo retirado ya superó la utilidad. Ese número **es** la advertencia.
- **La utilidad no se recalcula acá.** Se pide a `reports` por su función de integración: dos formas de calcular la misma utilidad terminan divergiendo, y este proyecto ya tuvo dos cifras contradiciéndose en la misma pantalla.

## 5. Qué se bloquea y qué solo se advierte

| Situación | Qué hace |
|---|---|
| Retirar más de lo que hay **en la cuenta** | **Se rechaza.** No es una política de negocio, es un imposible físico |
| Retirar más que la utilidad del período | **Se advierte.** El dueño puede retirar lo suyo y está en su derecho; la app le dice qué está haciendo |
| Aportar o retirar en una cuenta **por cobrar** | **Se rechaza.** Ese saldo todavía no existe |
| Efectivo con la caja cerrada | **Se rechaza** con `CASH_SESSION_NOT_OPEN` y modal con CTA a abrirla. Por transferencia funciona a cualquier hora — la sesión la exige el **tipo de cuenta**, no la operación |
| Retiro sin motivo | **Se rechaza** (422). Es plata que salió del negocio; dentro de seis meses alguien va a preguntar |
| Fecha futura | **Se rechaza**, contra el *hoy de la empresa* y nunca contra `current_date` (que es UTC) |

La asimetría con el desembolso de un préstamo —que **no** valida saldo, ver [`DECISIONES_PENDIENTES.md`](../../frontend-starter/docs/DECISIONES_PENDIENTES.md) §3— es deliberada: el argumento que sostiene aquella excepción es que un mostrador registra fuera de orden. Un retiro del dueño es un acto deliberado.

## 6. Permisos

Tres, y no uno, porque no son la misma decisión:

| Permiso | Qué autoriza | Especial |
|---|---|---|
| `capital.view` | Ver el patrimonio y el historial | no |
| `capital.contribute` | Meter plata al negocio | no |
| `capital.withdraw` | **Sacar** plata del negocio | **sí** |

Solo el **Admin** de fábrica. Cuánto puso el dueño y cuánto se ha llevado es información que se le enseña a un socio o a un contador, no al mostrador. Y `capital.withdraw` es la única operación de la app que le quita capital a la empresa sin nada a cambio.

## 7. Lo que este módulo **no** hace

- **No es un libro mayor.** No hay cuentas contables, ni asientos, ni balance. Construir partida doble sería reescribir la app para un caso que se resuelve con un documento y dos conceptos de caja.
- **No reparte entre socios.** Hay un "dueño", no una tabla de socios con porcentajes. El día que aparezca una sociedad real, `capital_movement` necesita una columna `partner_id` y nada más — la forma ya aguanta.
- **No calcula impuestos.** `kind` distingue utilidad de devolución de capital para que el contador pueda, no para que la app opine.
- **No cierra el ejercicio.** La utilidad se mide por período consultado, no hay "utilidades acumuladas" persistidas. Es coherente con el resto: *los saldos se derivan, nunca se guardan*.

## 8. Preguntas abiertas

1. **¿Hace falta un tope o una autorización por monto?** Hoy `capital.withdraw` es todo o nada. Es la misma pregunta que quedó abierta para el ajuste de arqueo en [`CAJA_TRAZABILIDAD.md`](CAJA_TRAZABILIDAD.md) §8.3, y conviene contestarlas juntas.
2. **¿El aporte debería poder ser en especie?** Un dueño que mete mercancía en vez de plata hoy lo registra como `initial_stock` (`00033`), que no lo vincula con su patrimonio. Nadie lo ha pedido.
3. **¿Un reporte de retorno sobre el capital invertido?** *"Puse 50M, he retirado 12M, el negocio vale X"* es el reporte que un dueño realmente quiere. `GET /capital/position` ya tiene las tres piezas; falta la pantalla que las ponga en el tiempo.
