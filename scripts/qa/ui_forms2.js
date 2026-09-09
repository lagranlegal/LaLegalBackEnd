const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const FORMS = [
  { name: 'Nueva venta',          path: '/ventas/nueva',                        btn: /^Vender/ },
  { name: 'Nuevo ingreso',        path: '/inventario/ingresos/nuevo',           btn: /^Registrar ingreso/ },
  { name: 'Nueva transformación', path: '/inventario/transformaciones/nueva',   btn: /^Transformar/ },
];
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:800}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);

  for (const f of FORMS) {
    await p.goto(BASE+f.path, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(4500);
    const handles = await p.$$('button');
    let target=null, label='', disabled=false;
    for (const h of handles) {
      const t = ((await h.textContent())||'').trim();
      if (f.btn.test(t) && await h.isVisible()) { target=h; label=t; disabled=await h.isDisabled(); }
    }
    if (!target) { console.log(`\n### ${f.name}: botón no encontrado`); continue; }
    console.log(`\n### ${f.name}   botón "${label}"${disabled?'  [DESHABILITADO]':''}`);
    if (disabled) {
      const pista = await p.evaluate(() => {
        const t = document.body.innerText;
        const m = t.match(/(agrega|elige|selecciona|debes|falta)[^\n]{0,80}/gi);
        return m ? m.slice(0,3) : [];
      });
      console.log(`  ¿dice por qué está deshabilitado? ${pista.length ? JSON.stringify(pista) : 'NO — ninguna pista en pantalla'}`);
      const title = await target.getAttribute('title');
      console.log(`  atributo title del botón: ${title || '(ninguno)'}`);
      continue;
    }
    await target.scrollIntoViewIfNeeded();
    const y0 = await p.evaluate(()=>window.scrollY);
    await target.click({force:true}).catch(()=>{});
    await p.waitForTimeout(2500);
    const r = await p.evaluate(() => {
      const vh=innerHeight, vis=e=>{const b=e.getBoundingClientRect();return b.top>=0&&b.bottom<=vh&&b.width>0};
      const nodes=[...document.querySelectorAll('p,span,div,li')].filter(e=>{
        const t=(e.textContent||'').trim(); if(!t||t.length>120||e.children.length) return false;
        const s=getComputedStyle(e);
        return /rgb\((2[0-5]\d|1[89]\d),\s*(\d{1,2}|1[01]\d),/.test(s.color) || e.getAttribute('role')==='alert';
      });
      return { y:scrollY, msgs:nodes.map(n=>n.textContent.trim()), vis:nodes.filter(vis).map(n=>n.textContent.trim()),
        toasts:[...document.querySelectorAll('[role=status],[data-sonner-toast],li[data-sonner-toast]')].map(n=>n.textContent.trim()),
        dialogs:document.querySelectorAll('[role=dialog]').length };
    });
    console.log(`  scrollY: ${y0} → ${r.y}`);
    console.log(`  mensajes en el DOM  : ${r.msgs.length?JSON.stringify(r.msgs.slice(0,3)):'(ninguno)'}`);
    console.log(`  VISIBLES sin scroll : ${r.vis.length?JSON.stringify(r.vis.slice(0,3)):'(NINGUNO)'}`);
    console.log(`  toasts: ${JSON.stringify(r.toasts)} · diálogos: ${r.dialogs}`);
  }
  await b.close();
})();
