const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:800}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  await p.goto(BASE+'/inventario/ingresos/nuevo', {waitUntil:'domcontentloaded'}); await p.waitForTimeout(4500);
  const btn = (await p.$$('button')).find ? null : null;
  for (const h of await p.$$('button')) {
    const t = ((await h.textContent())||'').trim();
    if (/^Registrar ingreso/.test(t) && await h.isVisible()) { await h.scrollIntoViewIfNeeded(); await h.click({force:true}); break; }
  }
  await p.waitForTimeout(2500);
  const r = await p.evaluate(() => {
    const vh = innerHeight;
    const nodes=[...document.querySelectorAll('p,span,div,li')].filter(e=>{
      const t=(e.textContent||'').trim(); if(!t||t.length>120||e.children.length) return false;
      return /rgb\((2[0-5]\d|1[89]\d),\s*(\d{1,2}|1[01]\d),/.test(getComputedStyle(e).color);
    });
    return {
      scrollY: scrollY, viewport: vh,
      errores: nodes.map(n => {
        const b = n.getBoundingClientRect();
        return { texto: n.textContent.trim().slice(0,50), docY: Math.round(b.top + scrollY), visible: b.top>=0 && b.bottom<=vh };
      }).sort((a,b)=>a.docY-b.docY),
      foco: document.activeElement ? (document.activeElement.getAttribute('name')||document.activeElement.getAttribute('placeholder')||document.activeElement.tagName) : null,
    };
  });
  console.log(`scrollY tras enviar: ${r.scrollY} · alto de ventana: ${r.viewport}`);
  console.log(`ventana visible del documento: ${r.scrollY} … ${r.scrollY + r.viewport}\n`);
  console.log('errores ordenados por posición en el documento:');
  for (const e of r.errores) console.log(`  y=${String(e.docY).padStart(5)}  ${e.visible?'VISIBLE ':'fuera   '} ${e.texto}`);
  console.log(`\nfoco tras enviar: ${r.foco}`);
  await b.close();
})();
