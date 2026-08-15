# CONTEXTO DEL PROYECTO — Plataforma SaaS para Compraventas
> Archivo de traspaso de contexto. Adjuntar en un chat nuevo para continuar el trabajo con todo el contexto.
> Última actualización: 14/08/2026. Interlocutor: Teo (mateojaras@gmail.com).
> Despliegue decidido: **Vercel** (front) + **Fly.io** (backend) + **Supabase** (BD/Auth/Storage). Migraciones: **Supabase CLI** (SQL versionado aplicado por CI).

## 1. Qué es el proyecto
Aplicación administrativa para compraventas (casas de empeño + tienda) que evolucionó a **plataforma SaaS multi-tenant**: se vende por suscripción a otras compraventas. Dos dominios de negocio que operan de forma independiente en la misma app con **contabilidad separada**:
- **Contratos (Empeño):** contratos de empeño, abonos, intereses, prórrogas, remates.
- **Inventario (Tienda):** venta de joyas, tecnología, etc., con categorías y códigos.

**Stack decidido:** React (SPA, Vite+TS), FastAPI (Python), Supabase (PostgreSQL + Auth + Storage + RLS).

## 2. Arquitectura — DECIDIDA: Ruta A
Se evaluaron 3 rutas; **el cliente aprobó la Ruta A**: monolito modular multi-tenant, una sola BD compartida, toda tabla de negocio con `company_id` y aislamiento por **RLS** (política `company_id = jwt.company_id`). FastAPI organizado en módulos internos (contracts, inventory, cashbox, customers, identity, billing, platform). Escrituras de negocio siempre por FastAPI; lecturas simples pueden ir directo React→Supabase (PostgREST) protegidas por RLS. Rutas descartadas: B (schema por tenant), C (microservicios) — quedan como evolución futura posible.
- Auth: Supabase Auth (correo/contraseña + Google OAuth), custom claims `company_id` y `role_id` en el JWT.
- Storage: buckets privados por empresa, URLs firmadas (cédulas, fotos, contratos firmados).
- Infra sugerida: FastAPI en Railway/Render/Fly (Docker), front en Vercel/Netlify, 3 entornos (dev/staging/prod). Migraciones versionadas (Supabase CLI o Alembic). Habeas Data (Ley 1581 Colombia).

## 3. Reglas de negocio DECIDIDAS (con el cliente)
### Intereses y abonos
- Interés mensual = **tasa del contrato × saldo de capital ACTUAL**. Ej.: $1.000.000 al 5% → $50.000/mes; abona $250.000 → $50.000 interés + $200.000 capital → nuevo saldo $800.000 → interés siguiente $40.000. Cálculo 100% automático.
- **DECIDIDO: solo se aceptan meses COMPLETOS de interés** — el parcial se rechaza. El capital solo se abona cuando los intereses quedan al día (en el mismo pago que los salda o después). La UI guía con los montos exactos aceptables.
- **Ventana de mora parametrizable por categoría** (metales 4 meses, tecnología 1 — misma regla, distinta ventana), editable por el rol admin. **Snapshot legal:** cada contrato congela sus términos (tasa, plazo, ventana) al crearse; los cambios de configuración solo aplican a contratos nuevos.
- Descuento sobre intereses: SOLO admin (permiso especial), motivo obligatorio, auditado.

### Máquina de estados del contrato (automática, nadie la cambia a mano)
- **VIGENTE:** intereses al día. Pagando solo el interés mensual se mantiene vigente indefinidamente.
- **EN MORA:** debe 1–3 meses de interés. Cada mes pagado "desbloquea" un mes (debe 3 → paga 1 → debe 2).
- **PRÓRROGA:** al acumular 4 meses sin pagar interés se dispara automáticamente 1 mes final.
- **REMATADO:** pasa 1 día de la prórroga sin pagar → pierde el producto (vía remate asistido, no automático).
- **PAGADO:** salda capital + intereses; los artículos se devuelven TODOS juntos; cierra el contrato.
- Migración: un solo consecutivo nuevo; contratos antiguos conservan su código en campo "Código anterior".
- Firma empresarial: imagen/PDF cargada en configuración, se inserta automáticamente en el PDF de todos los contratos nuevos. Cliente firma el impreso (fase 1); firma en pantalla = fase 2.
- Plazos por defecto por categoría: 4 meses metales, 1 mes tecnología. LTV (% máx. préstamo) por categoría: advertencia, no bloqueo.

### Remate — DECIDIDO: asistido
Decisión humana, ejecución automática. Sistema lista contratos "listos para remate" (prórroga vencida) → usuario con permiso ejecuta "Rematar" → sistema crea automáticamente artículo de inventario en **BORRADOR** (costo = saldo capital + intereses, vínculo bidireccional al contrato, ingreso de inventario, auditoría) → usuario completa precio/fotos y publica. Descartados: remate automático por fecha y remate manual puro.

### Artículo de contrato vs. artículo de inventario
Entidades DISTINTAS: art. contrato = prenda en garantía (categoría+descripción+peso/serial, sin precio ni stock; estados: custodia/devuelto/rematado). Art. inventario = producto en venta (código, precio, stock, fotos). El campo "Artículo generado por remate" en art. contrato es solo vínculo de trazabilidad, se llena automático al rematar. En UI: nombres y formularios separados ("Prenda en garantía" vs "Artículo de tienda").

### Categorías — árbol de 3 niveles dinámico
Principal (Joyería, Tecnología) → Secundaria (Oro, Plata) → Terciaria (Cadena, Anillo). Todas creadas dinámicamente por empresa. Cada una con letra de código (1–3 chars, única entre hermanas de la rama). No se eliminan con histórico: se inactivan. Catálogo compartido empeño+tienda.

### Codificación de artículos de inventario
`[Letra Cat1][Cat2][Cat3][Consecutivo 4 dígitos][Letra proveedor | R]` → **DECIDIDO:** consecutivo 0001 y sufijo **R** para remates. Ej.: **JOC0001I** (compra a proveedor I) / **JOC0001R** (remate). Consecutivo por prefijo+empresa con contador transaccional. Código ≠ id técnico (UUID), inmutable una vez emitido. **Costos DECIDIDOS:** identificación específica — cada pieza/lote conserva su costo real de compra (estándar joyero, NIIF); accesorios por lote FIFO; nunca promediar.

### Venta vs. Movimiento de caja
Venta = documento comercial (detalle, stock, comprobante). Movimiento de caja = libro del dinero, **generado automáticamente** desde cada operación (venta, abono, préstamo, compra), etiquetado por módulo EMPEÑO/TIENDA + medio de pago + referencia al documento. Manual en caja: solo gastos y ajustes. Nada se digita dos veces.

### Cierre de caja — DECIDIDO
UN solo acto de apertura/cierre diario con **base ÚNICA de efectivo** y **desglose contable por módulo** en el acta (sección EMPEÑO, sección TIENDA, gastos, otros medios/conciliación). Sin tolerancia de diferencias: todo descuadre exige justificación y alimenta el histórico por responsable. El modelo conserva cash_register para multi-caja/sucursal en fase 2. Sin sesión abierta no hay operaciones de dinero. Cierre inmutable; reapertura con permiso especial auditado. No abrir nuevo día con sesión anterior abierta.

### Otras decisiones cerradas (14/08/2026)
- **Ventas:** comprobante interno, sin DIAN por ahora.
- **Egresos y gastos:** quien tiene el permiso no requiere aprobación de admin; registro completo en auditoría (quién, cuándo, qué, motivo).
- **Suscripciones:** gestión 100% manual con precios internos. El cliente paga por fuera del sistema; el super-admin crea la empresa + habilita módulos/permisos, o amplía la fecha de vencimiento (expires_at). Job diario marca vencidas y bloquea acceso. Sin pasarela.
- **Tasación:** opcional (por artículo o total). LTV iniciales recomendados: oro 70%, plata 60%, tecnología 40% (advertencia, configurable por categoría).
- **Matriz de permisos:** la de la hoja es la inicial; el admin puede modificarla en cualquier momento (RBAC dinámico ya diseñado).
- **Sucursales:** sin sedes hoy; diseño listo para activar multi-sucursal en F2 sin migración (tabla branch + branch_id nullable en cash_register y app_user; consecutivos siguen por empresa).

### Roles y permisos (RBAC dinámico)
- Catálogo global de permisos módulo×acción (ver/crear/editar/anular) + especiales: aplicar_descuento, rematar_contrato, anular_venta, egreso_inventario, abrir_cerrar_caja, reabrir_cierre.
- Roles por empresa, dinámicos (crear/clonar/editar); roles semilla: **Admin** (todo, incl. caja), **Moderador** (como admin pero NO ingresa inventario), **Asesor** (contratos, abonos, ventas, ver inventario e historial clientes), **Bodega** (inventario, ingresos, compras). + **Super-admin** de plataforma (empresas y suscripciones, no operativa).
- Flujo decidido: admin invita por correo con rol → empleado activa cuenta (contraseña o Google) → permisos SIEMPRE vía rol (nunca sueltos por usuario; se clona rol si hace falta) → cambios efecto inmediato + auditoría → salvaguardas (mín. 1 admin activo, no auto-degradarse, semilla no eliminables).
- Autorización: dependencia FastAPI por endpoint + RLS + UI solo oculta.

### Multi-empresa y suscripciones
Entidades: empresa, plan (módulos habilitados, límite usuarios, precio), suscripción (estados: Prueba, Activa, Morosa, Suspendida, Cancelada). Suspender = bloquear acceso sin borrar datos. Fase 1 cobro manual desde panel super-admin; fase 2 pasarela (Wompi/PayU/Stripe).

## 4. Módulos de la app
Contratos, Inventario, Clientes (ficha única + historial cruzado contratos+compras), Proveedores, Caja/Contabilidad (movimientos, gastos, cierres), Usuarios, Roles y Permisos, Reportes/Dashboard, Auditoría (log inmutable de acciones sensibles), Configuración de empresa (logo, firma, parámetros), Panel super-admin (empresas, suscripciones). Fase 2: notificaciones, sucursales/multi-caja, estado de cliente automático, firma en pantalla, DIAN, MFA.

## 5. Roadmap (fases)
- **F0 Fundaciones:** multi-tenant, Auth, RBAC, panel super-admin mínimo, CI/CD.
- **F1 Empeño+Caja:** clientes, categorías, contratos, abonos/estados, PDFs, caja y cierre diario, auditoría, configuración.
- **F2 Tienda:** proveedores, inventario+codificación, ingresos/egresos, ventas, remate asistido, cierre integrado.
- **F3 Plataforma comercial:** suscripciones completas, reportes/dashboard, onboarding.
- **F4 Fase 2 funcional:** firma pantalla, notificaciones, DIAN, sucursales, pasarela, MFA.

## 6. Dudas AÚN PENDIENTES con el cliente (casi todo cerrado el 14/08/2026)
1. ¿Venta de mostrador sin cliente permitida? (recomendado: sí, cliente opcional). Política de devoluciones de ventas.
2. Recategorización de artículo: propuesta "el código emitido no cambia" — validar formalmente.
3. Celdas DEFINIR de la matriz de permisos para Moderador (rematar / caja / reportes) — es matriz inicial editable, pero conviene fijar el arranque.
4. Insumos no técnicos para F0: nombre/marca y dominio de la plataforma, proveedor de correo transaccional (recomendado Resend o SMTP propio en Supabase Auth), datos de la empresa piloto, cuentas de GitHub/Supabase/Fly/Vercel.

## 7. Entregables ya producidos (en la carpeta del proyecto)
1. **Analisis_Arquitectura_Compraventa_SaaS.docx** (v1.1, 13 págs.): visión, módulos, definiciones funcionales (secciones 3.4 estados/intereses, 3.5 remate asistido, 3.6 venta vs caja, 3.7 cierre, 3.8 suscripciones), 3 rutas de arquitectura + comparativa (Ruta A aprobada), modelo de datos, seguridad, roadmap, riesgos, pendientes.
2. **Campos_y_Procesos_Compraventa_v3.xlsx** (v3.1, 24 hojas): definición campo a campo por hoja/tabla con columnas # / Campo / Descripción / Tipo / Obligatorio / Origen / Duda / Confirma cliente / Observaciones. Hojas: Indice, Cliente, Contrato, Articulo Contrato, Categoria Articulo, Abono Pago Contrato, **Estados del Contrato**, Usuario, Rol y Permisos, Proveedor, Articulo Inventario, Ingreso/Egreso Inventario, Venta, Movimiento Caja, Apertura Cierre Caja, Gasto, Matriz de Permisos, Empresa, Suscripcion, Sucursal, Auditoria, Codificacion Consecutivos, Dashboard Reportes. Colores: amarillo = validar con cliente, verde claro = nuevo, naranja = pendiente de análisis.
3. **Historias_de_Usuario_Compraventa_SaaS.docx** (v1.0, 12 págs.): 55 historias en 15 épicas (E1–E15) con criterios de aceptación y fase asignada, más DoD global (permisos+RLS+auditoría+tests).
4. **Arquitectura_BD_Backend_Compraventa_SaaS.docx** (v1.1, 15 págs., documento de ejecución): convenciones de BD, esquema completo por dominios (plataforma, identidad, clientes, catálogos, contratos, inventario/ventas, caja, auditoría) con columnas y reglas, patrón RLS y de consecutivos (SQL), dónde vive cada regla (BD vs servicio), estructura FastAPI por módulos y capas, auth JWKS + require_permission, convenciones de API e idempotencia, flujos críticos (abono, remate, venta, cierre), checklist de seguridad OWASP/Habeas Data, endurecimiento de Supabase (signups off/invitación, Turnstile, JWKS, custom access token hook, Supavisor en modo transacción con claims por TX, network restrictions, storage RLS por company_id, 3 proyectos por entorno, PITR), despliegue Vercel+Fly.io+CI GitHub Actions, estándares de código, plan de sprints S1–S5 y registro de decisiones cerradas (sección 9).
5. **Campos_y_Procesos_Compraventa_v3.xlsx** ahora en v3.2: decisiones del 14/08 aplicadas en verde en las hojas correspondientes.

## 8. Próximos pasos sugeridos
1. Validar con el cliente las dudas de la sección 6 (usar las hojas amarillas del Excel).
2. Diseñar el esquema SQL detallado (DDL + políticas RLS) a partir del modelo del documento de arquitectura.
3. Montar F0: proyecto Supabase, esqueleto FastAPI modular, React base, CI/CD, seeds (permisos, roles semilla).
4. Refinar y estimar las historias de F0/F1 para el primer sprint.
