// Verifica EN VIVO el aviso de cupo del LTV en el formulario de contrato.
//
// Por qué existe: el aviso está detrás de tres condiciones —una categoría
// elegida, un avalúo y un monto—, así que encontrar el texto en el JS servido
// prueba que se desplegó, NO que se ve. Y el texto cambia según el permiso
// `contracts.override_ltv`, que es justo la diferencia que importa.
//
// Playwright no es dependencia del proyecto: se resuelve desde el caché de
// npx (ver ESTADO.md, "Trampas del entorno").
//
//   node scripts/qa/ui_ltv.js <email>
const { chromium } = require(process.env.QA_PLAYWRIGHT
  || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);

const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const PW = process.env.QA_PASSWORD || 'QaLab2026!';
const [email] = process.argv.slice(2);

const texto = async (page) => (await page.textContent('body')) || '';

// El Chromium que descarga Playwright PUEDE NO ESTAR: el caché de
// `~/Library/Caches/ms-playwright` se vacía al limpiar o al actualizar la
// copia de npx, y entonces `launch()` falla pidiendo `playwright install`.
// Pasó el 11/09/2026, con ESTADO.md afirmando que estaba descargado — la
// misma clase de afirmación con fecha de vencimiento que el proyecto ya
// tiene escrita como principio. Se cae al Chrome del sistema, que no
// requiere descargar nada.
async function abrirNavegador() {
  try {
    return await chromium.launch();
  } catch (e) {
    if (!/Executable doesn't exist/.test(String(e))) throw e;
    console.log('  (sin Chromium de Playwright — usando el Chrome del sistema)');
    return chromium.launch({ channel: 'chrome' });
  }
}

(async () => {
  const browser = await abrirNavegador();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 1100 } });
  const page = await ctx.newPage();
  const errores = [];
  page.on('console', (m) => { if (m.type() === 'error') errores.push(m.text().slice(0, 140)); });

  await page.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await page.fill('input[type=email]', email);
  await page.fill('input[type=password]', PW);
  await page.click('button[type=submit]');
  await page.waitForURL((u) => !u.pathname.startsWith('/auth'), { timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(2500);

  await page.goto(`${BASE}/contratos/nuevo`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(4000);

  // Antes de tocar nada NO debe afirmar nada: sin categoría ni avalúo no hay
  // cupo que calcular, y un aviso ahí sería inventado.
  const t0 = await texto(page);
  console.log('\n### Formulario recién abierto');
  console.log(`  ${t0.includes('Puede prestar hasta') || t0.includes('Supera el cupo') ? 'MAL' : 'OK '} no afirma nada sin datos`);

  // --- Elegir la categoría de la primera prenda ---------------------------
  // El tope sale de ESTA categoría (el backend usa la de la primera prenda).
  const selects = await page.$$('button[role=combobox]');
  console.log(`\n  selects encontrados: ${selects.length}`);
  let categoriaElegida = null;
  for (const s of selects) {
    await s.click().catch(() => {});
    await page.waitForTimeout(700);
    const opciones = await page.$$('[role=option]');
    if (!opciones.length) { await page.keyboard.press('Escape'); continue; }
    const etiquetas = [];
    for (const o of opciones) etiquetas.push(((await o.textContent()) || '').trim());
    // La de categorías es la que ofrece hojas de empeño.
    const idx = etiquetas.findIndex((e) => e && !/efectivo|transferencia|otro/i.test(e));
    if (idx >= 0 && etiquetas.length > 1) {
      await opciones[idx].click();
      categoriaElegida = etiquetas[idx];
      await page.waitForTimeout(600);
      break;
    }
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
  }
  console.log(`  categoría elegida: ${categoriaElegida ?? '(ninguna)'}`);

  // --- Monto y avalúo -----------------------------------------------------
  const llenar = async (id, valor) => {
    const el = await page.$(`#${id}`);
    if (!el) return false;
    await el.click();
    await el.fill('');
    await page.keyboard.type(valor, { delay: 30 });
    await page.waitForTimeout(700);
    return true;
  };

  await llenar('principal', '1000000');
  const hayAvaluo = await llenar('appraisal_value', '2000000');
  console.log(`  campo de avalúo: ${hayAvaluo ? 'llenado' : 'NO ENCONTRADO'}`);

  const t1 = await texto(page);
  console.log('\n### Con categoría, monto 1.000.000 y avalúo 2.000.000');
  const dentro = t1.includes('Puede prestar hasta');
  const excede = t1.includes('Supera el cupo de la garantía');
  console.log(`  ${dentro || excede ? 'SI ' : 'NO '} aparece el aviso de cupo`);
  console.log(`  estado: ${excede ? 'EXCEDE' : dentro ? 'DENTRO' : '(ninguno)'}`);
  if (excede) {
    console.log(`  ${t1.includes('Tu rol no puede registrar') ? 'SI ' : 'NO '} explica el bloqueo (rol sin override_ltv)`);
    console.log(`  ${t1.includes('queda marcado como excedido') ? 'SI ' : 'NO '} explica la autorización (rol con override_ltv)`);
  }
  const m = t1.match(/(Puede prestar hasta[^.]*\.|Supera el cupo de la garantía en [^\n]{0,40})/);
  if (m) console.log(`  texto: "${m[0].trim().slice(0, 120)}"`);

  // --- Subir el monto muy por encima --------------------------------------
  await llenar('principal', '9000000');
  const t2 = await texto(page);
  console.log('\n### Subiendo el monto a 9.000.000');
  console.log(`  ${t2.includes('Supera el cupo de la garantía') ? 'SI ' : 'NO '} ahora avisa que se pasa`);

  // --- Quitar el avalúo: el aviso debe DESAPARECER ------------------------
  if (hayAvaluo) {
    await llenar('appraisal_value', '');
    const t3 = await texto(page);
    console.log('\n### Sin avalúo');
    console.log(`  ${t3.includes('Puede prestar hasta') || t3.includes('Supera el cupo') ? 'MAL' : 'OK '} el aviso desaparece (nada que comparar)`);
  }

  // Desborde horizontal a 360 px — el patrón que ya costó caro (F6-03).
  await page.setViewportSize({ width: 360, height: 900 });
  await page.waitForTimeout(1200);
  const desborde = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  console.log(`\n  desborde a 360px: ${desborde}px ${desborde > 0 ? '← REVISAR' : '(ninguno)'}`);
  console.log(`  errores de consola: ${errores.length ? errores.join(' | ') : '(ninguno)'}`);

  await browser.close();
})();
