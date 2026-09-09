const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const PAGADO = process.argv[2];
async function imprimir(p, regex) {
  await p.evaluate(() => { window.print = () => { window.__imp = true; }; window.__imp = false; });
  for (const h of await p.$$('button')) {
    const t = ((await h.textContent())||'').trim();
    if (regex.test(t) && await h.isVisible()) {
      if (await h.isDisabled()) return { estado: `«${t}» está DESHABILITADO` };
      await h.click(); await p.waitForTimeout(2500);
      await p.emulateMedia({ media: 'print' }); await p.waitForTimeout(700);
      const r = await p.evaluate(() => ({ imp: window.__imp, texto: (document.body.innerText||'').replace(/\n{3,}/g,'\n\n').trim() }));
      await p.emulateMedia({ media: 'screen' });
      return { estado: `print() = ${r.imp}`, texto: r.texto };
    }
  }
  return { estado: 'botón no encontrado' };
}
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);

  // 1. Paz y salvo
  await p.goto(`${BASE}/contratos/${PAGADO}`, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(7000);
  let r = await imprimir(p, /paz y salvo/i);
  console.log(`\n### PAZ Y SALVO — ${r.estado}`);
  if (r.texto) console.log(r.texto.slice(0, 420));

  // 2. Comprobante de venta: abrir el detalle de la primera fila
  await p.goto(`${BASE}/ventas`, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(6000);
  const filas = await p.$$('tbody tr');
  if (filas.length) { await filas[0].click(); await p.waitForTimeout(3500); }
  r = await imprimir(p, /imprimir|comprobante/i);
  console.log(`\n### COMPROBANTE DE VENTA — ${r.estado}`);
  if (r.texto) console.log(r.texto.slice(0, 420));

  await b.close();
})();
