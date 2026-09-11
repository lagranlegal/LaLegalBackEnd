// Verificación EN VIVO del despliegue del 11/09/2026 (los cinco puntos que
// trajo Mateo de probar con el cliente), contra el backend DESPLEGADO.
//
// Por qué existe: un `fly deploy` verde dice que el proceso arrancó, no que
// las reglas nuevas se comporten. Y tres de los cinco cambios son de
// comportamiento (el buscador, la herencia del ancla, los permisos del
// módulo nuevo), o sea que solo se prueban ejerciéndolos.
//
//   node scripts/qa/verificar_despliegue_11_09.js
const API = process.env.QA_API_URL || 'https://compraventa-backend-dev.fly.dev';
const PW = process.env.QA_PASSWORD || 'QaLab2026!';
const SUPA = 'https://driyubkodnsqxbtxcmaz.supabase.co';
const ANON = process.env.QA_ANON_KEY;

let ok = 0, mal = 0;
const check = (cond, etiqueta, detalle = '') => {
  console.log(`  ${cond ? 'OK ' : 'MAL'} ${etiqueta}${detalle ? ` — ${detalle}` : ''}`);
  cond ? ok++ : mal++;
};

async function login(email) {
  const r = await fetch(`${SUPA}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: ANON, 'content-type': 'application/json' },
    body: JSON.stringify({ email, password: PW }),
  });
  const j = await r.json();
  if (!j.access_token) throw new Error(`login ${email}: ${JSON.stringify(j).slice(0, 200)}`);
  return j.access_token;
}

const get = async (token, ruta) => {
  const r = await fetch(`${API}${ruta}`, { headers: { Authorization: `Bearer ${token}` } });
  return { status: r.status, body: await r.json().catch(() => null) };
};

const post = async (token, ruta, body) => {
  const r = await fetch(`${API}${ruta}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'content-type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify(body),
  });
  return { status: r.status, body: await r.json().catch(() => null) };
};

(async () => {
  const admin = await login('qa.admin@qalab.com');
  const asesor = await login('qa.asesor@qalab.com');

  // --- 1. El buscador filtra desde la TERCERA letra ----------------------
  console.log('\n### 1. Buscadores (fix del "solo desde la quinta letra")');
  const todos = await get(admin, '/api/v1/customers?limit=50');
  const conNombre = (todos.body?.items || []).find((c) => (c.full_name || '').split(' ')[0].length >= 5);
  if (!conNombre) {
    console.log('  (sin clientes con nombre de 5+ letras en el laboratorio — se salta)');
  } else {
    const nombre = conNombre.full_name.split(' ')[0];
    const tres = nombre.slice(0, 3).toLowerCase();
    const r = await get(admin, `/api/v1/customers?q=${encodeURIComponent(tres)}&limit=50`);
    const encontrado = (r.body?.items || []).some((c) => c.id === conNombre.id);
    check(encontrado, `"${tres}" encuentra a ${conNombre.full_name}`);

    // El riesgo NUEVO del cambio: `to_tsquery` es sintaxis y `plainto_tsquery`
    // no lo era. Un `&` suelto sería un SyntaxError -> 500 en el buscador.
    for (const raro of ['&', '(', ':*', 'de la', '!!!']) {
      const s = await get(admin, `/api/v1/customers?q=${encodeURIComponent(raro)}`);
      check(s.status === 200, `q=${JSON.stringify(raro)} no revienta`, `status ${s.status}`);
    }
  }

  // El piso va POR CLÁUSULA: el número de contrato desde la PRIMERA tecla.
  const contratos = await get(admin, '/api/v1/contracts?limit=50');
  const algunContrato = (contratos.body?.items || [])[0];
  if (algunContrato) {
    const primeraTecla = String(algunContrato.number)[0];
    const r = await get(admin, `/api/v1/contracts?q=${primeraTecla}&limit=200`);
    const esta = (r.body?.items || []).some((c) => c.id === algunContrato.id);
    check(esta, `el nº de contrato se encuentra con 1 carácter ("${primeraTecla}")`);
  }

  // --- 2. El recargo conserva la fecha del original ----------------------
  console.log('\n### 2. El recargo hereda el ancla (00053/00055)');
  const vivos = (contratos.body?.items || []).filter((c) =>
    ['active', 'in_arrears', 'in_extension'].includes(c.status));
  check(vivos.length > 0 && vivos.every((c) => c.extension_interest_policy === 'keep_anchor'),
    `los ${vivos.length} contratos vivos están en keep_anchor`);

  const cerrados = (contratos.body?.items || []).filter((c) =>
    ['paid', 'auctioned', 'superseded'].includes(c.status));
  check(cerrados.every((c) => c.extension_interest_policy === 'forgive'),
    `los ${cerrados.length} cerrados quedaron intactos en forgive`);

  // Los campos nuevos existen y son null en un contrato que no nació de un
  // recargo — así `extended_on is not null` responde "¿es un sucesor?".
  const noSucesor = (contratos.body?.items || []).find((c) => !c.parent_contract_id);
  if (noSucesor) {
    check('extended_on' in noSucesor && noSucesor.extended_on === null,
      'extended_on es null en un contrato que no es sucesor');
  }

  // El recargo de verdad: sobre un contrato vivo con cupo y ventana abierta.
  let ampliado = null;
  for (const c of vivos) {
    const cupo = await get(admin, `/api/v1/contracts/${c.id}/extension-options`);
    if (cupo.body?.is_open && Number(cupo.body.available) > 1000) {
      const antes = await get(admin, `/api/v1/contracts/${c.id}`);
      const r = await post(admin, `/api/v1/contracts/${c.id}/extend-loan`,
        { amount: '1000.00', payment_method: 'transfer', account_id: null });
      if (r.status === 201) {
        ampliado = { antes: antes.body, despues: r.body };
        break;
      }
      console.log(`    (contrato #${c.number}: ${r.status} ${r.body?.code || ''})`);
    }
  }
  if (!ampliado) {
    console.log('  (ningún contrato con ventana abierta y cupo — no se pudo ejercer el recargo)');
  } else {
    const { antes, despues } = ampliado;
    check(despues.start_date === antes.start_date,
      'el sucesor conserva la fecha del original', `${antes.start_date} → ${despues.start_date}`);
    check(despues.interest_paid_until === antes.interest_paid_until,
      'el ancla del interés no se movió', despues.interest_paid_until);
    check(despues.due_date === antes.due_date, 'el plazo no se reinició');
    check(despues.extended_on !== null && despues.extended_on !== despues.start_date,
      'extended_on registra el día REAL del recargo',
      `contrato ${despues.start_date} · recargo ${despues.extended_on}`);
    check(despues.extension_amount === '1000.00', 'extension_amount guarda el delta');
  }

  // --- 3 y 4. El módulo de capital --------------------------------------
  console.log('\n### 3 y 4. Capital del dueño (00054)');
  const pos = await get(admin, '/api/v1/capital/position?from_date=2026-01-01&to_date=2026-12-31');
  check(pos.status === 200, 'GET /capital/position responde', `status ${pos.status}`);
  if (pos.status === 200) {
    const p = pos.body;
    const suma = ['cash_and_bank', 'loan_portfolio', 'inventory_at_cost']
      .reduce((a, k) => a + Number(p[k]), 0);
    check(Math.abs(suma - Number(p.total_capital)) < 0.01,
      'total_capital = disponible + prestado + inventario',
      `${p.cash_and_bank} + ${p.loan_portfolio} + ${p.inventory_at_cost} = ${p.total_capital}`);
    check(Number(p.loan_portfolio) > 0, 'la cartera prestada NO es cero', p.loan_portfolio);
  }

  // La utilidad NO puede moverse por un aporte: es patrimonio, no resultado.
  const antesPyG = await get(admin, '/api/v1/reports/income-statement?from_date=2026-01-01&to_date=2026-12-31');
  const cuentas = await get(admin, '/api/v1/accounts');
  const banco = (cuentas.body || []).find((a) => a.type === 'bank' && a.active);
  if (!banco) {
    console.log('  (sin cuenta de banco activa — se salta el aporte)');
  } else {
    const aporte = await post(admin, '/api/v1/capital/contributions',
      { account_id: banco.id, amount: '1000000.00', notes: 'Verificación de despliegue' });
    check(aporte.status === 201, 'POST /capital/contributions', `status ${aporte.status} ${aporte.body?.code || ''}`);
    if (aporte.status === 201) {
      check(aporte.body.kind === null, 'un aporte no lleva `kind`');
      const despuesPyG = await get(admin, '/api/v1/reports/income-statement?from_date=2026-01-01&to_date=2026-12-31');
      check(antesPyG.body.operating_profit === despuesPyG.body.operating_profit,
        'EL APORTE NO ES UN INGRESO: la utilidad no se movió',
        `${antesPyG.body.operating_profit} → ${despuesPyG.body.operating_profit}`);

      const retiro = await post(admin, '/api/v1/capital/withdrawals',
        { account_id: banco.id, amount: '500000.00', notes: 'Verificación de despliegue' });
      check(retiro.status === 201, 'POST /capital/withdrawals', `status ${retiro.status}`);
      if (retiro.status === 201) {
        const finalPyG = await get(admin, '/api/v1/reports/income-statement?from_date=2026-01-01&to_date=2026-12-31');
        check(antesPyG.body.operating_expenses === finalPyG.body.operating_expenses,
          'EL RETIRO NO ES UN GASTO: los gastos no se movieron',
          `${antesPyG.body.operating_expenses} → ${finalPyG.body.operating_expenses}`);
        check(retiro.body.kind === 'profit', 'el retiro toma el default `profit`');
      }
    }
  }

  const sinMotivo = await post(admin, '/api/v1/capital/withdrawals',
    { account_id: banco?.id, amount: '1000.00' });
  check(sinMotivo.status === 422, 'un retiro sin motivo se rechaza', `status ${sinMotivo.status}`);

  const imposible = await post(admin, '/api/v1/capital/withdrawals',
    { account_id: banco?.id, amount: '999999999.00', notes: 'todo' });
  check(imposible.status === 400, 'retirar más de lo que hay se rechaza', `status ${imposible.status}`);

  // El permiso, que es lo que separa a este módulo del resto.
  console.log('\n### Permisos del módulo nuevo');
  const asesorVe = await get(asesor, '/api/v1/capital/movements');
  check(asesorVe.status === 403, 'el Asesor NO puede ver el capital del dueño',
    `status ${asesorVe.status}`);
  const asesorRetira = await post(asesor, '/api/v1/capital/withdrawals',
    { account_id: banco?.id, amount: '1000.00', notes: 'x' });
  check(asesorRetira.status === 403, 'el Asesor NO puede retirar', `status ${asesorRetira.status}`);

  const hist = await get(admin, '/api/v1/capital/movements');
  check(hist.status === 200, 'el historial responde', `status ${hist.status}`);
  if (hist.status === 200 && hist.body.items.length > 1) {
    const fechas = hist.body.items.map((m) => m.movement_date);
    const ordenado = [...fechas].sort().reverse().join() === fechas.join();
    check(ordenado, 'el historial sale del más reciente al más antiguo');
  }

  console.log(`\n=== ${ok} OK · ${mal} MAL ===`);
  process.exit(mal ? 1 : 0);
})().catch((e) => { console.error('FALLÓ:', e.message); process.exit(2); });
