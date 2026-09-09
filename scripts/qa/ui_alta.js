const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const LINK = process.argv[2], EMAIL = process.argv[3], PASS = 'NuevaClave2026!';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0,120)));
  console.log('1. Abriendo el enlace en un navegador real, DESPUÉS de los 4 crawlers…');
  await p.goto(LINK, {waitUntil:'domcontentloaded'});
  await p.waitForTimeout(6000);
  const t1 = await p.evaluate(() => (document.body.innerText||'').split('\n').filter(x=>x.trim()).slice(0,10));
  console.log('   pantalla:', t1.join(' | ').slice(0,180));
  console.log('   url:', p.url().replace(/\?.*/,'?…').slice(0,80));
  const campos = await p.$$('input[type=password]');
  console.log(`   campos de contraseña: ${campos.length}`);
  if (!campos.length) { console.log('   → no llegó a la pantalla de crear contraseña'); await b.close(); return; }
  console.log('\n2. Poniendo la contraseña…');
  for (const c of campos) await c.fill(PASS);
  for (const h of await p.$$('button')) {
    const t = ((await h.textContent())||'').trim();
    if (/guardar|crear|continuar|entrar/i.test(t) && await h.isVisible()) { await h.click(); break; }
  }
  await p.waitForTimeout(8000);
  const t2 = await p.evaluate(() => ({ url: location.pathname, texto: (document.body.innerText||'').split('\n').filter(x=>x.trim()).slice(0,8) }));
  console.log(`   → ${t2.url}`);
  console.log('   ', t2.texto.join(' | ').slice(0,150));
  console.log(`\n3. ¿Entró a la app? ${!t2.url.startsWith('/auth')}`);
  if (errs.length) console.log('   errores:', errs.slice(0,2).join(' | '));
  await b.close();
})();
