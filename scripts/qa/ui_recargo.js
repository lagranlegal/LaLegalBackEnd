// Verifica en la app EN VIVO la pantalla de ampliar préstamo (00051).
//
// Por qué existe: el bundle puede tener los textos y la pantalla igual no
// mostrarlos —el panel está detrás de un permiso, de un cupo y de un motivo
// de bloqueo—. Buscar la cadena en el JS servido prueba que se desplegó, no
// que se ve.
//
// Playwright no es dependencia del proyecto: se resuelve desde el caché de
// npx (ver ESTADO.md, "Trampas del entorno").
//
//   node scripts/qa/ui_recargo.js <email> <contrato_viejo_id> <contrato_nuevo_id>
const { chromium } = require(process.env.QA_PLAYWRIGHT
  || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);

const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const PW = process.env.QA_PASSWORD || 'QaLab2026!';
const [email, viejoId, nuevoId] = process.argv.slice(2);

const texto = async (page) => (await page.textContent('body')) || '';

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await ctx.newPage();
  const errores = [];
  page.on('console', (m) => { if (m.type() === 'error') errores.push(m.text().slice(0, 140)); });

  await page.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await page.fill('input[type=email]', email);
  await page.fill('input[type=password]', PW);
  await page.click('button[type=submit]');
  await page.waitForURL((u) => !u.pathname.startsWith('/auth'), { timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(2500);

  // --- El contrato AMPLIADO: tiene que decir que ya no rige ---------------
  await page.goto(`${BASE}/contratos/${viejoId}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3500);
  const t1 = await texto(page);
  console.log('\n### Contrato ampliado (el viejo)');
  for (const [q, esperado] of [
    ['badge "Ampliado"', 'Ampliado'],
    ['aviso de que dejó de regir', 'dejó de ser la obligación vigente'],
    ['prenda "Pasó al nuevo contrato"', 'Pasó al nuevo contrato'],
  ]) console.log(`  ${t1.includes(esperado) ? 'SI ' : 'NO '} ${q}`);
  // El panel NO debe aparecer en un contrato cerrado: no hay nada que explicar.
  console.log(`  ${t1.includes('Ampliar el préstamo') ? 'MAL' : 'OK '} el panel NO aparece`);

  // --- El contrato SUCESOR: la cadena y el panel --------------------------
  await page.goto(`${BASE}/contratos/${nuevoId}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3500);
  const t2 = await texto(page);
  console.log('\n### Contrato sucesor (el nuevo)');
  for (const [q, esperado] of [
    ['link al contrato anterior', 'Ver el contrato anterior'],
    ['panel de ampliar', 'Ampliar el préstamo'],
    ['cupo a la vista', 'Puede retirar hasta'],
  ]) console.log(`  ${t2.includes(esperado) ? 'SI ' : 'NO '} ${q}`);
  // Este ya agotó el cupo: el panel debe EXPLICARLO, no desaparecer.
  console.log(`  ${t2.includes('llegó al tope del avalúo') ? 'SI ' : 'NO '} explica por qué no se puede`);

  // Desborde horizontal del documento a 360 px — el patrón que ya costó caro.
  await page.setViewportSize({ width: 360, height: 800 });
  await page.waitForTimeout(1200);
  const desborde = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  console.log(`\n  desborde a 360px: ${desborde}px ${desborde > 0 ? '← REVISAR' : '(ninguno)'}`);
  console.log(`  errores de consola: ${errores.length ? errores.join(' | ') : '(ninguno)'}`);

  await browser.close();
})();
