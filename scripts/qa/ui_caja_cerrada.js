//   node scripts/qa/ui_caja_cerrada.js <contract_id>
//
// Necesita un contrato con ventana de recargo ABIERTA en una empresa con la
// caja CERRADA (el laboratorio usa `ZZ QA-B`, que no abre turno).
//
// El punto 5 tal como lo reportó el cliente: "no muestra un mensaje
// informativo explicando el porqué". Lo único que prueba el arreglo es VER
// el mensaje, así que esto va por navegador y no por API.
const { chromium } = require(`${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = 'https://la-legal-front-end.vercel.app';
const ID = process.argv[2];
let ok = 0, mal = 0;
const ck = (c, t, d = '') => { console.log(`  ${c ? 'OK ' : 'MAL'} ${t}${d ? ` — ${d}` : ''}`); c ? ok++ : mal++; };

(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch { browser = await chromium.launch({ channel: 'chrome' }); }
  const page = await (await browser.newContext({ viewport: { width: 1400, height: 1300 } })).newPage();
  const txt = async () => (await page.textContent('body')) || '';

  await page.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await page.fill('input[type=email]', 'qa.b.admin@qalab.com');
  await page.fill('input[type=password]', 'QaLab2026!');
  await page.click('button[type=submit]');
  await page.waitForURL((u) => !u.pathname.startsWith('/auth'), { timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(3000);

  await page.goto(`${BASE}/contratos/${ID}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(5000);

  console.log('\n### El aviso PREVENTIVO (lo que evita el callejón sin salida)');
  const t = await txt();
  ck(t.includes('Ampliar el préstamo'), 'el panel del recargo está');
  ck(/La caja está cerrada/i.test(t), 'avisa que la caja está cerrada ANTES de llenar nada');
  ck(/transferencia/i.test(t), 'y dice la salida: se puede por transferencia');

  console.log('\n### Y si igual se intenta en efectivo');
  // Monto -> abrir confirmación -> confirmar. El 409 tiene que producir el
  // modal central, no el silencio de antes.
  const monto = await page.$('#extend-amount');
  if (!monto) { ck(false, 'no se encontró el campo de monto'); }
  else {
    await monto.fill('100000');
    await page.waitForTimeout(600);
    const botones = await page.$$('button');
    for (const b of botones) {
      if ((await b.textContent() || '').trim() === 'Ampliar préstamo') { await b.click(); break; }
    }
    await page.waitForTimeout(1200);
    for (const b of await page.$$('button')) {
      if (/Ampliar y entregar/.test(await b.textContent() || '')) { await b.click(); break; }
    }
    await page.waitForTimeout(3500);
    const t2 = await txt();
    ck(/Caja cerrada/i.test(t2), 'sale el modal "Caja cerrada"');
    ck(/Esta operación necesita una sesión de caja abierta/i.test(t2), 'explica el porqué');
    ck(/Abrir caja/i.test(t2), 'ofrece la salida (CTA para abrirla)');
    await page.screenshot({ path: '/private/tmp/claude-501/-Users-mateojaramillo-projects-compraventa-app/bd308fa7-f24d-4f26-9819-3033520180fe/scratchpad/caja_cerrada.png' });
  }

  console.log('\n### El buscador de clientes, en pantalla');
  await page.goto(`${BASE}/contratos/nuevo`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(4000);
  const buscador = await page.$('input[type=search]');
  if (!buscador) { ck(false, 'no se encontró el buscador de cliente'); }
  else {
    await buscador.fill('cl');
    await page.waitForTimeout(1500);
    ck(/Escribe al menos 3 letras/i.test(await txt()), 'con 2 letras dice qué falta, no "Sin resultados"');
    await buscador.fill('cli');
    await page.waitForTimeout(2500);
    const t3 = await txt();
    ck(!/Escribe al menos 3 letras/i.test(t3), 'con 3 letras ya consulta');
    ck(/Cliente/i.test(t3), 'y encuentra', 'con tres letras');
  }

  console.log(`\n=== ${ok} OK · ${mal} MAL ===`);
  await browser.close();
  process.exit(mal ? 1 : 0);
})().catch((e) => { console.error('FALLÓ:', e.message); process.exit(2); });
