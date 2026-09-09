const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const CONTRATO = process.argv[2];
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  const errores = [];
  p.on('console', m => { if (m.type()==='error') errores.push(m.text().slice(0,140)); });
  p.on('pageerror', e => errores.push('PAGEERROR: ' + String(e).slice(0,140)));
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  await p.goto(`${BASE}/contratos/${CONTRATO}`, {waitUntil:'domcontentloaded'});
  await p.waitForTimeout(7000);
  const botones = await p.evaluate(() => [...document.querySelectorAll('button')].filter(b=>b.offsetParent).map(b=>`${(b.textContent||'').trim().slice(0,26)}${b.disabled?' [disabled]':''}`));
  console.log('botones del detalle:', botones.filter(t=>t).join(' · '));
  // buscar el de imprimir
  let imp=null;
  for (const h of await p.$$('button')) {
    const t=((await h.textContent())||'').trim();
    if (/imprimir/i.test(t) && await h.isVisible()) imp=h;
  }
  if (!imp) { console.log('\n(no se encontró botón de imprimir)'); await b.close(); return; }
  console.log(`\n¿el botón está habilitado? ${!(await imp.isDisabled())}  ← el fix del 28/08 lo deshabilita hasta que la plantilla cargue`);
  await imp.click();
  await p.waitForTimeout(3500);
  const r = await p.evaluate(() => {
    const pl = document.querySelector('[data-print-layout], .print-layout, [class*=print]');
    const cont = pl || document.body;
    return { hayLayout: !!pl, texto: (cont.innerText||'').replace(/\n{2,}/g,'\n').slice(0,700), dialogos: document.querySelectorAll('[role=dialog]').length };
  });
  console.log(`\n¿se montó una vista de impresión? ${r.hayLayout} · diálogos abiertos: ${r.dialogos}`);
  console.log('--- contenido visible ---');
  console.log(r.texto);
  if (errores.length) console.log('\nERRORES DE CONSOLA:', errores.slice(0,4).join('\n  '));
  await p.screenshot({path:'print_vacia.png', fullPage:true});
  await b.close();
})();
