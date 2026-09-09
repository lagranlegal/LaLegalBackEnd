const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const RUTAS = ['/', '/contratos', '/ventas', '/ventas/nueva', '/inventario', '/clientes', '/caja', '/cuentas', '/reportes', '/identidad', '/auditoria', '/configuracion'];
const ANCHOS = [360, 768, 1280];
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  console.log(`${'ruta'.padEnd(22)} ${ANCHOS.map(a=>String(a).padStart(12)).join('')}`);
  for (const ruta of RUTAS) {
    const celdas = [];
    for (const w of ANCHOS) {
      await p.setViewportSize({width:w, height:800});
      await p.goto(BASE+ruta, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(2200);
      const r = await p.evaluate(() => {
        const de = document.documentElement;
        const desborde = de.scrollWidth - de.clientWidth;
        // elementos que se salen del viewport por la derecha
        const fuera = [...document.querySelectorAll('body *')].filter(e => {
          const b = e.getBoundingClientRect();
          return b.width > 0 && b.right > de.clientWidth + 2 && getComputedStyle(e).position !== 'fixed';
        }).length;
        // ¿hay algún táctil menor a 44px? (WCAG/iOS)
        const chicos = [...document.querySelectorAll('button,a[href]')].filter(e=>{
          const b=e.getBoundingClientRect();
          return b.width>0 && b.height>0 && b.height<32;
        }).length;
        return {desborde, fuera, chicos};
      });
      celdas.push(r.desborde > 0 ? `DESB ${r.desborde}px` : (r.fuera ? `${r.fuera} fuera` : 'ok'));
    }
    console.log(`${ruta.padEnd(22)} ${celdas.map(c=>c.padStart(12)).join('')}`);
  }
  await b.close();
})();
