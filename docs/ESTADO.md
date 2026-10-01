# Estado — 30/09/2026

> **Corto y vivo.** Se **reemplaza** en cada sesión, no se apila: lo que deja de ser cierto se borra (git guarda
> la historia). Las cifras llevan la fecha en que se midieron. Qué es Prendo y el mapa de documentos:
> [`README.md`](README.md).

## 1. Dónde estamos

- **Solo existe dev** (`dev.prendo.com.co` / `api-dev.prendo.com.co`). Los datos de la empresa del primer cliente
  en dev son **de prueba** (Mateo, 30/09): no hay nada de producción todavía. **Producción es el único bloqueante
  para vender**; el paso a paso está en [`PRODUCCION.md`](PRODUCCION.md) (§0: las decisiones previas).
- **Auditoría integral** (plan: [`PLAN_AUDITORIA_INTEGRAL.md`](PLAN_AUDITORIA_INTEGRAL.md)): hechas las fases
  1–15 y las tandas de arreglos A, B, D, E, F1, F2, F3, G, G2, H (back y front) e I (front), todas desplegadas en
  dev y verificadas en navegador. Recomendaciones: [`RECOMENDACIONES.md`](RECOMENDACIONES.md). Los bugs abiertos
  viven en GitHub Issues con la etiqueta `auditoría-2026-09` ([`QA.md`](QA.md) §4). Fase 16 (rediseño visual):
  Mateo aprobó la propuesta el 30/09; **P1 (tokens y componentes compartidos) desplegada**; siguen P2 (Inicio con
  «Para hoy», detalle de contrato, punto de venta, lista de contratos, búsqueda global) y P3 (el resto).
- **Último deploy:** backend `ca420cd` (migraciones hasta 00066); front `9dc1a10` (rediseño P1 y formularios con el
  campo compartido). CI en verde en los dos repos.
- **Suites (30/09):** backend 971 passed (más 1 intermitente conocido), front 801.
- **Avisos por correo:** todo construido y desplegado; los avisos al cliente nacen apagados por empresa. El
  comprobante pedido en el mostrador (`send_receipt_email` en ventas y abonos) se manda aunque el cliente no haya
  autorizado avisos, pero respeta el interruptor general de correos de la empresa ([`DOMINIO.md`](DOMINIO.md) §9.2).
- Tamaño (30/09): 66 migraciones, 14 módulos backend. Se recuentan, no se copian.

## 2. Lo que espera a Mateo (no es código)

1. Las **decisiones del rediseño** (fase 16) y las previas a producción ([`PRODUCCION.md`](PRODUCCION.md) §0).
2. Crear o redirigir el buzón **`contacto@prendo.com.co`** (la landing lo publica).
3. Antes de encender avisos al cliente en una empresa real: la cláusula de autorización en su plantilla de
   contrato e, idealmente, una revisión legal.
4. DMARC y prueba de spam.
5. Pasar los repos a privados cuando el plan de Vercel lo permita.

## 3. Qué falta (código)

Issues abiertas con la etiqueta `auditoría-2026-09` (24 del backend; en el front, las que no cerró la tanda I).
Lo siguiente: el rediseño P2 (pantallas de mostrador, idénticas a la §5 de la propuesta) y P3 — para el Inicio
el backend ya trae `GET /contracts/attention` («Para hoy», con `contracts.view`), y el dashboard del Admin trae el mes
anterior para comparar; falta la pantalla. Para la lista de contratos (issue #10 del front, P2-d), `GET /contracts`
ya trae `customer_name`/`customer_document` y `?sort=` (`next_due_asc` por defecto; API_GUIDE §7) —sin desplegar, el
front tiene que regenerar tipos y volver a la primera página al cambiar de orden—. Falta la
casilla «Enviar comprobante» del POS y del abono (necesita que el backend exponga el interruptor general de
correos a quien vende); `pip-audit`.

## 4. Decisiones de negocio abiertas

- **Descuento sobre intereses en un abono**: el backend lo soporta (`payments.apply_discount`) y no hay pantalla.
  ¿Se construye, se retira el permiso? ¿Con tope? ¿Motivo libre o de lista?
- **Desembolsar más efectivo del que hay en el cajón**: el préstamo y el gasto no validan saldo; el traslado y el
  retiro sí. Opción recomendada: advertir, o un permiso para pasarse (como `override_ltv`).
- **`sales.return_override_time_limit`**: el permiso existe y ninguna pantalla avisa del plazo vencido.
- **Moderador con `contracts.override_ltv` y `contracts.extend_loan`**: por el criterio de su propia lista de
  exclusiones, no deberían estar.
- **Recordatorios**: tope o autorización por monto en retiros de capital y ajustes de arqueo; alerta de descuadre de
  arqueo como quinto tipo; correo certificado para R5.

## 5. Trampas que muerden primero

Guardar no es aplicar · el deploy es `./scripts/deploy_dev.sh`, nunca `fly deploy` pelado · la Machine del job no
se destruye · dos bases (tests local, todo lo demás remoto) · el ref de Supabase sale de `SUPABASE_URL` · nunca
`supabase config push` · lecturas a la remota con `BEGIN TRANSACTION READ ONLY` · backend antes que front, salvo
que una migración exija el front nuevo. Detalle: [`OPERACION.md`](OPERACION.md) §4.

## 6. Qué leer

| Si vas a… | Lee |
|---|---|
| entender el producto y las piezas | [`README.md`](README.md) |
| tocar reglas de plata, estados o reportes | [`DOMINIO.md`](DOMINIO.md) |
| tocar la estructura del backend | [`ARQUITECTURA.md`](ARQUITECTURA.md) y `../CLAUDE.md` |
| integrar un endpoint o un código de error | [`API_GUIDE.md`](API_GUIDE.md) |
| desplegar o diagnosticar | [`OPERACION.md`](OPERACION.md) |
| montar producción | [`PRODUCCION.md`](PRODUCCION.md) |
| probar o reportar un bug | [`QA.md`](QA.md) |
| qué mejorar frente a apps profesionales | [`RECOMENDACIONES.md`](RECOMENDACIONES.md) |
