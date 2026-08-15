// Valida las migraciones y el seed contra PGlite (Postgres real en WASM).
// Uso: node test_migrations.mjs  (requiere: npm i @electric-sql/pglite)
import { PGlite } from "@electric-sql/pglite";
import { readFileSync, readdirSync } from "fs";
import { join } from "path";

const dir = process.env.MIG_DIR || "./supabase/migrations";
const db = new PGlite();

// Shims de entorno Supabase que PGlite no trae (solo para el test local):
await db.exec(`
  create schema if not exists auth;
  create role supabase_auth_admin;
`).catch(() => db.exec(`create schema if not exists auth;`));

const files = readdirSync(dir).filter(f => f.endsWith(".sql")).sort();
for (const f of files) {
  let sql = readFileSync(join(dir, f), "utf8");
  // pgcrypto no es necesario en PG>=13 para gen_random_uuid
  sql = sql.replace(/create extension if not exists pgcrypto;/g, "");
  try {
    await db.exec(sql);
    console.log("OK  ", f);
  } catch (e) {
    console.error("FAIL", f, "→", e.message);
    process.exit(1);
  }
}

// Seed
try {
  await db.exec(readFileSync("./supabase/seed.sql", "utf8"));
  console.log("OK   seed.sql");
} catch (e) {
  console.error("FAIL seed.sql →", e.message);
  process.exit(1);
}

// ---- Smoke test funcional: RLS + contadores + reglas -----------------
const claims = (cid) => `select set_config('request.jwt.claims', '{"company_id":"${cid}","sub":"00000000-0000-0000-0000-00000000aaaa"}', false);`;

// Nota: PGlite corre como superusuario (bypassa RLS), así que aquí validamos
// sintaxis/estructura y lógica de funciones; el aislamiento real se prueba en
// CI contra Supabase local con el rol authenticated (tests/rls del backend).
const a = (await db.query(`insert into company (name) values ('CV Uno') returning id`)).rows[0].id;
const b = (await db.query(`insert into company (name) values ('CV Dos') returning id`)).rows[0].id;

// current_company_id() lee los claims
await db.exec(claims(a));
const cur = (await db.query(`select public.current_company_id() as c`)).rows[0].c;
if (cur !== a) throw new Error("current_company_id no coincide");
console.log("OK   current_company_id() con claims por sesión/tx");

// Contador atómico
const n1 = (await db.query(`select public.next_counter('${a}','JOC') as n`)).rows[0].n;
const n2 = (await db.query(`select public.next_counter('${a}','JOC') as n`)).rows[0].n;
const nb = (await db.query(`select public.next_counter('${b}','JOC') as n`)).rows[0].n;
if (n1 !== 1 || n2 !== 2 || nb !== 1) throw new Error("next_counter mal");
console.log("OK   next_counter por empresa+prefijo (1,2 / 1)");

// Árbol de categorías: nivel inválido debe fallar
const c1 = (await db.query(`insert into category (company_id, level, name, code_letter) values ('${a}',1,'Joyeria','J') returning id`)).rows[0].id;
let failed = false;
try {
  await db.query(`insert into category (company_id, parent_id, level, name, code_letter) values ('${a}','${c1}',3,'Oro','O')`);
} catch { failed = true; }
if (!failed) throw new Error("trigger de nivel no valida");
const c2 = (await db.query(`insert into category (company_id, parent_id, level, name, code_letter) values ('${a}','${c1}',2,'Oro','O') returning id`)).rows[0].id;
await db.query(`insert into category (company_id, parent_id, level, name, code_letter) values ('${a}','${c2}',3,'Cadena','C')`);
console.log("OK   árbol de categorías: 3 niveles validados por trigger");

// Sesión de caja: única abierta por caja
const reg = (await db.query(`insert into cash_register (company_id) values ('${a}') returning id`)).rows[0].id;
await db.query(`insert into cash_session (company_id, register_id, opened_by, opening_balance) values ('${a}','${reg}','00000000-0000-0000-0000-00000000aaaa',100000)`);
failed = false;
try {
  await db.query(`insert into cash_session (company_id, register_id, session_date, opened_by, opening_balance) values ('${a}','${reg}', current_date+1,'00000000-0000-0000-0000-00000000aaaa',0)`);
} catch { failed = true; }
if (!failed) throw new Error("permite dos sesiones abiertas");
console.log("OK   cash_session: solo una sesión abierta por caja");

// Inmutabilidad de auditoría
await db.query(`insert into audit_log (company_id, module, action, entity_type) values ('${a}','test','create','x')`);
failed = false;
try { await db.query(`delete from audit_log`); } catch { failed = true; }
if (!failed) throw new Error("audit_log editable");
console.log("OK   audit_log inmutable (trigger)");

console.log("\\nTODO OK — esquema válido y lógica de BD verificada.");
