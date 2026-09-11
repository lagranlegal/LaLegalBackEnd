// Ejerce el recargo EN VIVO sobre un contrato con fecha PASADA (00053).
//
// POR QUÉ IMPORTA QUE SEA PASADA: si el contrato empezó HOY, heredar la
// fecha y ponerla en hoy dan el mismo resultado, así que la prueba no
// distinguiría el comportamiento nuevo del viejo. El contrato se siembra por
// `POST /contracts/import`, que es el único camino que acepta `start_date`.
//
// Deja un contrato de prueba en el laboratorio (legacy_code `VERIF-*`).
//
//   QA_ANON_KEY=... node scripts/qa/verificar_recargo_ancla.js
const API = 'https://compraventa-backend-dev.fly.dev';
const SUPA = 'https://driyubkodnsqxbtxcmaz.supabase.co';
const ANON = process.env.QA_ANON_KEY, PW = 'QaLab2026!';

const j = async (r) => ({ status: r.status, body: await r.json().catch(() => null) });
(async () => {
  const auth = await (await fetch(`${SUPA}/auth/v1/token?grant_type=password`, {
    method: 'POST', headers: { apikey: ANON, 'content-type': 'application/json' },
    body: JSON.stringify({ email: 'qa.admin@qalab.com', password: PW }),
  })).json();
  const T = auth.access_token;
  const H = () => ({ Authorization: `Bearer ${T}`, 'content-type': 'application/json', 'Idempotency-Key': crypto.randomUUID() });
  const get = async (p) => j(await fetch(`${API}${p}`, { headers: { Authorization: `Bearer ${T}` } }));
  const post = async (p, b) => j(await fetch(`${API}${p}`, { method: 'POST', headers: H(), body: JSON.stringify(b) }));

  const cli = (await get('/api/v1/customers?limit=1')).body.items[0];
  const cats = (await get('/api/v1/catalogs/categories')).body;
  const hoja = JSON.stringify(cats).match(/"id":"([0-9a-f-]{36})"[^}]*"level":3/);
  const nivel3 = (function find(ns) {
    for (const n of ns || []) { if (n.level === 3) return n; const r = find(n.children); if (r) return r; }
  })(Array.isArray(cats) ? cats : cats.items);
  const catId = nivel3.id;

  // Contrato con fecha de hace 20 días: ventana (28d) abierta y el ancla en
  // el pasado, que es lo que hace visible la herencia.
  const d = new Date(Date.now() - 20 * 864e5).toISOString().slice(0, 10);
  const imp = await post('/api/v1/contracts/import', {
    legacy_code: `VERIF-${Date.now()}`, customer_id: cli.id,
    principal: '1000000.00', capital_balance: '1000000.00', appraisal_value: '5000000.00',
    interest_rate_pct: '5', term_months: 3, arrears_window_months: 4,
    start_date: d, interest_paid_until: d,
    items: [{ category_id: catId, description: 'Prenda de verificación', item_appraisal: '5000000.00' }],
  });
  if (imp.status !== 201) return console.log('import falló:', imp.status, JSON.stringify(imp.body).slice(0, 300));
  const antes = imp.body;
  console.log(`contrato #${antes.number} — start_date ${antes.start_date} · política ${antes.extension_interest_policy}`);

  const cupo = await get(`/api/v1/contracts/${antes.id}/extension-options`);
  console.log(`cupo: disponible ${cupo.body.available} · abierto ${cupo.body.is_open} · ${cupo.body.blocked_reason || 'sin bloqueo'}`);
  if (!cupo.body.is_open) return;

  const r = await post(`/api/v1/contracts/${antes.id}/extend-loan`,
    { amount: '500000.00', payment_method: 'transfer', account_id: null });
  if (r.status !== 201) return console.log('recargo falló:', r.status, JSON.stringify(r.body).slice(0, 300));
  const n = r.body;

  const hoy = new Date().toISOString().slice(0, 10);
  const ck = (c, t, d2 = '') => console.log(`  ${c ? 'OK ' : 'MAL'} ${t}${d2 ? ` — ${d2}` : ''}`);
  console.log('\n### El recargo, ejercido en vivo');
  ck(n.start_date === antes.start_date, 'el sucesor conserva la fecha del ORIGINAL', `${antes.start_date} → ${n.start_date}`);
  ck(n.start_date !== hoy, 'y NO es hoy (que es lo que hacía antes)', `hoy es ${hoy}`);
  ck(n.interest_paid_until === antes.interest_paid_until, 'el ancla del interés no se movió', n.interest_paid_until);
  ck(n.due_date === antes.due_date, 'el plazo no se reinició', n.due_date);
  ck(n.capital_balance === '1500000.00', 'el capital creció al nuevo', n.capital_balance);
  ck(n.extended_on === hoy, 'extended_on registra el día REAL del recargo', n.extended_on);
  ck(n.extension_amount === '500000.00', 'extension_amount guarda el DELTA, no el total', n.extension_amount);
  ck(n.status === 'active', 'el sucesor nace al día, no en mora', n.status);
  ck(n.signed_photo_url === null, 'nace sin foto firmada: hay que imprimirlo');
  const viejo = (await get(`/api/v1/contracts/${antes.id}`)).body;
  ck(viejo.status === 'superseded', 'el viejo quedó superseded');
  ck(viejo.items.every((i) => i.status === 'transferred'), 'las prendas quedaron transferred, no returned');
  console.log(`\n  El cliente sigue pagando el día ${n.start_date.slice(8)}, ahora sobre ${n.capital_balance}.`);
})();
