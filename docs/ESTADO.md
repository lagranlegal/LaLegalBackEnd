# Estado — 29/09/2026

> **Corto y vivo.** Se **reemplaza** en cada sesión, no se apila: lo que deja de ser cierto se borra (git guarda
> la historia). Las cifras llevan la fecha en que se midieron. Qué es Prendo y el mapa de documentos:
> [`README.md`](README.md).

## 1. Dónde estamos

- **Solo existe dev** (`dev.prendo.com.co` / `api-dev.prendo.com.co`), y el primer cliente opera ahí con datos
  reales. **Producción es el único bloqueante para vender**; el paso a paso está en [`PRODUCCION.md`](PRODUCCION.md)
  y Mateo lo dejó a propósito para cuando haya un segundo cliente.
- **Auditoría integral en curso** (plan: [`PLAN_AUDITORIA_INTEGRAL.md`](PLAN_AUDITORIA_INTEGRAL.md)). Hechas las
  fases 1–8, 10, 11 (documentación consolidada en los dos repos; en el front quedan `CLAUDE.md`,
  `docs/ARQUITECTURA.md` y `docs/DESIGN_SYSTEM.md`), 12 y 13, y las tandas de arreglos A, B, D, E, F1, F2 y G.
  Faltan: 9 (UI/UX, informe entregado, arreglos pendientes), 14 recomendaciones, 15 bugs a GitHub Issues + E2E
  versionada, 16 rediseño visual.
- **Último deploy verificado en navegador:** 29/09 08:15 — backend `af8affe` (migraciones hasta 00064), front
  `16a37d5`; 9/9 comprobaciones, 0 errores de JS, 0 respuestas 5xx. **Después hay commits de la fase 8 en los dos
  repos** (plantilla activa no vaciable, piso de la Ley 2300, comprobantes fuera del tope diario, Storage de perfil
  con 00065, subtotales del estado de resultados): verificar qué está servido antes de asumirlo
  ([`OPERACION.md`](OPERACION.md) §4.1).
- **Suites (29/09):** backend 949 passed (por tramos, más 1 intermitente conocido), front 543.
- **Avisos por correo:** todo construido y desplegado; **ninguna empresa manda avisos al cliente** (nacen
  apagados); la invitación de usuario sale siempre por Resend.
- Tamaño (29/09): 65 migraciones, 15 módulos backend, 43 permisos. Se recuentan, no se copian.

## 2. Lo que espera a Mateo (no es código)

1. **Seguridad P0-1**: el paso descrito en `SEGURIDAD_PRIVADO.md` (raíz del workspace, fuera del repo).
2. **Desplegar** lo commiteado después de `af8affe`: `supabase db push --linked` → `./scripts/deploy_dev.sh` →
   push del front ([`OPERACION.md`](OPERACION.md) §2).
3. Crear o redirigir el buzón **`contacto@prendo.com.co`** (la landing lo publica y hoy no recibe).
4. Encender avisos por empresa; en el primer cliente, después de agregar la cláusula de autorización a su plantilla
   de contrato y, idealmente, de una revisión legal. Pedir el correo del cliente en el mostrador (hoy lo tienen 2
   de 16).
5. Decirle al primer cliente que su cajón quedó en negativo por abrir sin registrar el efectivo inicial.
6. Publicar la guía de usuario revisada y mover el pin del kit de identidad (`marca/`).
7. DMARC y prueba de spam.

## 3. Qué falta (código)

Lista única de bugs abiertos: [`QA.md`](QA.md) §4. Lo siguiente, en orden: desplegar y verificar lo de la fase 8;
arreglos de la fase 9 que sean altos; pasar los abiertos a GitHub Issues; rediseño visual (propuesta primero).

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
`supabase config push` · lecturas a la remota con `BEGIN TRANSACTION READ ONLY` · backend antes que front · datos
del primer cliente intocables. Detalle: [`OPERACION.md`](OPERACION.md) §4.

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
