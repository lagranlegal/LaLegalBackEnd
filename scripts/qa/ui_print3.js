const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const DESTINOS = JSON.parse(process.argv[2]);
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  const errores = [];
  p.on('pageerror', e => errores.push(String(e).slice(0,120)));
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);

  for (const d of DESTINOS) {
    await p.emulateMedia({ media: 'screen' });
    await p.goto(BASE + d.ruta, {waitUntil:'domcontentloaded'});
    await p.waitForTimeout(6000);
    await p.evaluate(() => { window.print = () => { window.__imp = true; }; window.__imp = false; });
    // abrir un diálogo intermedio si hace falta (comprobante de venta, acta)
    if (d.abrir) {
      for (const h of await p.$$('button, tr, [role=row]')) {
        const t = ((await h.textContent())||'').trim();
        if (new RegExp(d.abrir, 'i').test(t) && await h.isVisible()) { await h.click(); await p.waitForTimeout(2500); break; }
      }
    }
    let hallado = false;
    for (const h of await p.$$('button')) {
      const t = ((await h.textContent())||'').trim();
      if (new RegExp(d.boton, 'i').test(t) && await h.isVisible() && !(await h.isDisabled())) {
        await h.click(); hallado = true; break;
      }
    }
    if (!hallado) { console.log(`\n### ${d.nombre}: no se encontró «${d.boton}» habilitado`); continue; }
    await p.waitForTimeout(2500);
    await p.emulateMedia({ media: 'print' });
    await p.waitForTimeout(700);
    const r = await p.evaluate(() => ({ imp: window.__imp, texto: (document.body.innerText||'').replace(/\n{3,}/g,'\n\n').trim() }));
    console.log(`\n### ${d.nombre}  (print() llamado: ${r.imp} · ${r.texto.length} chars)`);
    console.log(r.texto.slice(0, 520) || '(VACÍO)');
  }
  if (errores.length) console.log('\nERRORES:', errores.slice(0,3).join(' | '));
  await b.close();
})();
