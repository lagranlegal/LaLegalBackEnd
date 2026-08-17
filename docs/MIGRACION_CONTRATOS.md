# MIGRACION_CONTRATOS.md — Import de contratos pre-existentes (spec para backend)

> **Estado:** implementado (`POST /api/v1/contracts/import`, migración `00012_contract_import.sql`). Ver `docs/API_GUIDE.md` §7 para el contrato de API final.
> **Principio de diseño:** se migra la **foto financiera al corte**, no la historia.
> El body trae *hechos* del sistema viejo; todo lo derivable (estado, due_date,
> consecutivo, meses adeudados) lo calcula el backend con la lógica que YA existe
> (máquina de estados, recálculo en lectura, job nocturno). Cero cambios en
> abonos, estados o remate: un contrato importado se comporta igual que uno nativo
> desde el segundo después del import.

---

## 1. Cambio de BD (una sola migración nueva, p. ej. `00009_contract_import.sql`)

- Reemplazar el índice parcial `ix_contract_legacy` por un **UNIQUE**:

```sql
drop index if exists ix_contract_legacy;
create unique index ux_contract_legacy on public.contract (company_id, legacy_code)
  where legacy_code is not null;
```

- Nuevo permiso en el catálogo: **`contracts.import`**. Seed: asignado SOLO al rol
  Admin (los demás roles no lo reciben; se puede clonar rol si hace falta).
- Nada más. No se tocan tablas ni columnas: `legacy_code`, `start_date` manual,
  `capital_balance` e `interest_paid_until` ya existen para esto.

## 2. Endpoint

`POST /api/v1/contracts/import` — permiso `contracts.import`.

- Header **`Idempotency-Key` obligatorio** (recomendación operativa: usar el
  `legacy_code`). Reusa la columna `idempotency_key` nullable de `contract` y su
  `UNIQUE(company_id, idempotency_key)` existente: reenviar la misma key devuelve
  el mismo contrato, no duplica.
- **NO requiere sesión de caja abierta** y **NO genera `cash_movement`**: el
  desembolso ocurrió en el pasado, en el sistema anterior. Es la diferencia
  central con `POST /contracts`.
- Auditado (acción sensible): registrar `legacy_code`, `principal`,
  `capital_balance` y usuario en el log de auditoría.

### Body

```jsonc
{
  "legacy_code": "C-1042",            // OBLIGATORIO aquí (en /contracts es opcional)
  "customer_id": "uuid",              // el cliente debe existir (migrar clientes primero)
  "principal": 500000,                // lo prestado originalmente
  "capital_balance": 350000,          // saldo de capital HOY (> 0, ≤ principal)
  "interest_rate_pct": 5.0,           // SNAPSHOT: condiciones pactadas EN SU MOMENTO,
  "term_months": 4,                   //   vienen del contrato viejo, NUNCA de la
  "arrears_window_months": 4,         //   config actual de la categoría
  "extension_months": 1,
  "start_date": "2026-01-10",
  "interest_paid_until": "2026-06-10",// hasta dónde tiene intereses cubiertos
  "items": [                          // mismo shape que /contracts
    { "category_id": "uuid", "description": "Cadena oro 18k",
      "weight_grams": 12.5, "item_appraisal": 400000, "photos": [] }
  ],
  "appraisal_value": 400000,          // opcional
  "signed_photo_url": null,           // opcional (foto del contrato en papel)
  "notes": "Migrado del sistema anterior"  // opcional
}
```

### Lo que deriva el backend (no se acepta en el body)

| Campo | Derivación |
|---|---|
| `number` | `next_counter(company, 'CONTRACT')` — consecutivo nuevo normal; el código viejo vive en `legacy_code` (buscable). |
| `due_date` | `start_date + term_months` meses. |
| `status` | Se inserta `active` y se pasa por el **mismo recálculo** que usa `GET /contracts/{id}` y el job nocturno ANTES de responder → el response ya sale `active` / `in_arrears` / `in_extension` según las fechas. `extension_ends_at` lo fija ese recálculo si aplica. **Nunca aceptar `status` en el body**: un solo origen de verdad, imposible importar un estado inconsistente con sus fechas. |
| `ltv_warning` | Misma regla que la creación normal (si hay tasación). |
| `interest_type` | `simple_on_balance` (default). |
| `created_by` | Usuario autenticado. |

### Diferencias de reglas vs `POST /contracts`

- Los `items` deben ser categorías **nivel 3** (igual), pero **NO** se exige que
  compartan `default_term_months`/`arrears_window_months`: en el import, plazo y
  ventana vienen del body (del contrato viejo), no de la categoría.
- La tasa/plazo/ventana/prórroga NO se leen de la config actual: snapshot desde
  el body. Coherente con la filosofía de snapshot del proyecto.

## 3. Validaciones y errores

| Código | Condición |
|---|---|
| `409 CONTRACT_LEGACY_CODE_EXISTS` | Ya hay un contrato con ese `legacy_code` en la empresa (el UNIQUE lo respalda; capturar el conflicto y mapearlo). |
| `422 IMPORT_DATES_MISALIGNED` | `interest_paid_until` ≠ `start_date + N meses` exactos (N entero ≥ 0). El modelo solo entiende meses completos anclados al día de inicio; sin esta validación, `months_owed` se rompe silenciosamente. Puede estar en el futuro (pagó por adelantado): válido. |
| `422 IMPORT_CAPITAL_EXCEEDS_PRINCIPAL` | `capital_balance > principal` o `capital_balance ≤ 0`. |
| `400 BAD_REQUEST` | `start_date` en el futuro; `term_months`/`arrears_window_months`/`extension_months` ≤ 0; items vacíos; categoría no nivel 3. |
| `404 NOT_FOUND` | `customer_id` o `category_id` inexistentes (misma empresa vía RLS). |

Manejo de fin de mes: si `start_date` es día 29–31, usar la misma convención de
aritmética de meses que ya usa el cálculo de `due_date`/`months_owed` en
`contracts` (no inventar otra) y validar la alineación con esa misma función.

## 4. Escenarios cubiertos (por qué el diseño alcanza)

| Escenario al corte | Cómo entra | Qué hace la app sola |
|---|---|---|
| Al día, sin abonos | `capital_balance = principal`, `interest_paid_until` reciente | Estado `active`. |
| Con abonos a capital | `capital_balance < principal` | Interés futuro correcto: `simple_on_balance` calcula sobre saldo. No hace falta saber cuántos abonos hubo. |
| Pagó intereses por adelantado | `interest_paid_until` en el futuro | Válido; es lo mismo que produce un abono normal. |
| Debe N meses (en ventana) | `interest_paid_until` atrás | `payment-options` cotiza los meses adeudados; recálculo → `in_arrears`. |
| En prórroga | Fechas lo derivan | Recálculo → `in_extension` + `extension_ends_at`. |
| Prórroga vencida | Fechas lo derivan | Aparece de inmediato en `ready-for-auction`; el remate usa el flujo nuevo (con trazabilidad a inventario). **Sí se migran.** |
| Pagado / rematado en el sistema viejo | **NO se migra** | Historia cerrada; el historial del cliente "arranca" con sus contratos vivos. |
| Condiciones viejas ≠ config actual | Snapshot desde el body | Ningún conflicto con la config vigente. |
| Interés parcial pagado en el sistema viejo | Ver §5 | — |

## 5. Política para interés parcial pagado en el sistema viejo

El modelo solo acepta meses completos. Al migrar: `interest_paid_until` = último
mes **completo** cubierto. El excedente que el cliente ya pagó se le reconoce en
su **primer abono en la app** usando el descuento existente (`discount_amount` +
`discount_reason = "saldo a favor migración"`, permiso `payments.apply_discount`).
Cero cambios de modelo, queda auditado, no se cobra dos veces. Esto es política
operativa (documentarla al equipo), no código nuevo.

## 6. Qué NO se migra (decisión explícita)

- **Historial de abonos viejos.** `contract_payment` es inmutable, genera
  `cash_movement` y consume consecutivos de recibo: replicar historia pelea con
  las tres cosas. `capital_balance` + `interest_paid_until` resumen el pasado; el
  detalle queda en el sistema viejo (solo lectura), localizable por `legacy_code`.
- Contratos `paid` o rematados en el sistema viejo.

## 7. Tests requeridos (Definición de Hecho)

- **Unitarios:** validación de alineación de fechas (incl. fin de mes 29–31);
  derivación de `due_date`; estado derivado para cada fila de la tabla de
  escenarios (§4); `capital_balance` fuera de rango.
- **Integración:** import **sin** sesión de caja abierta → `201` (¡no `409
  CASH_SESSION_NOT_OPEN`!); tras el import **no existe ningún `cash_movement`**;
  `legacy_code` duplicado → `409`; retry con la misma `Idempotency-Key` → mismo
  contrato; abono normal sobre un contrato importado en mora (cotización de
  `payment-options` correcta contra los meses esperados); remate de un importado
  con prórroga vencida; permiso: rol sin `contracts.import` → `403`.
- **RLS:** cubierto por las policies existentes de `contract`/`contract_item`
  (verificar que el test de aislamiento pasa por el endpoint nuevo).
- **Auditoría:** registro verificado en test.

## 8. Checklist de corte operativo

1. Migrar/crear **clientes** primero (el endpoint exige `customer_id`).
2. Congelar el registro de contratos nuevos en el sistema viejo (idealmente fin
   de semana).
3. Exportar contratos **vivos** a Excel/CSV con las columnas del body (§2).
4. Cargar vía script fila por fila contra el endpoint, `Idempotency-Key =
   legacy_code` → re-ejecutable sin duplicar.
5. **Conciliación:** número de contratos y suma de `capital_balance` por estado,
   comparado contra el reporte del sistema viejo. Si no cuadra, no se opera.
6. Operar en la app. Sistema viejo queda en solo lectura.
7. Rezagados (el papel del cajón): formulario del front (§9), uno a uno.

## 9. Frontend (resumen para el otro repo)

Formulario **"Registrar contrato existente"**, separado del de creación normal:
campos extra (`legacy_code`, `start_date`, `interest_paid_until`,
`capital_balance`, tasa/plazo/ventana/prórroga manuales), sin cobro y sin exigir
caja abierta, visible solo con `contracts.import`. En la lista y el detalle de
contratos, mostrar `legacy_code` como badge y hacerlo buscable (el índice ya
existe).

## 10. Al implementar

Agregar la fila del endpoint a `API_GUIDE.md` §7 y una línea en `CLAUDE.md`
(paso 5 ya menciona "migrados (legacy_code)" — apuntar a este doc).
