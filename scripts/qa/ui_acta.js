const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  await p.goto(BASE+'/caja', {waitUntil:'domcontentloaded'}); await p.waitForTimeout(6000);
  // buscar el histórico de cierres y abrir el del 08/09
  const filas = await p.$$('tbody tr');
  console.log(`filas en el histórico de cierres: ${filas.length}`);
  if (filas.length) {
    const txt = await filas[0].textContent();
    console.log(`primera fila: ${(txt||'').trim().slice(0,90)}`);
    await filas[0].click(); await p.waitForTimeout(3000);
  }
  await p.evaluate(() => { window.print = () => { window.__imp = true; }; window.__imp = false; });
  let ok = false;
  for (const h of await p.$$('button')) {
    const t = ((await h.textContent())||'').trim();
    if (/imprimir|acta/i.test(t) && await h.isVisible() && !(await h.isDisabled())) { await h.click(); ok = true; break; }
  }
  console.log(`¿botón de acta encontrado? ${ok}`);
  if (!ok) {
    const btns = await p.evaluate(() => [...document.querySelectorAll('button')].filter(b=>b.offsetParent).map(b=>(b.textContent||'').trim().slice(0,30)));
    console.log('botones disponibles:', btns.filter(x=>x).join(' · '));
    await b.close(); return;
  }
  await p.waitForTimeout(2500);
  await p.emulateMedia({ media: 'print' }); await p.waitForTimeout(700);
  const r = await p.evaluate(() => ({ imp: window.__imp, texto: (document.body.innerText||'').replace(/\n{3,}/g,'\n\n').trim() }));
  console.log(`\nprint() = ${r.imp}\n--- acta ---`);
  console.log(r.texto.slice(0, 400));
  await b.close();
})();
