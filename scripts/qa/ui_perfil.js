const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const EMAIL='qa.nuevo.09@qalab.com', VIEJA='NuevaClave2026!', NUEVA='CambiadaQA2026!';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]', EMAIL); await p.fill('input[type=password]', VIEJA);
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  console.log('login con la contraseña recién creada:', !p.url().includes('/auth') ? 'OK' : 'FALLÓ');

  await p.goto(BASE+'/perfil', {waitUntil:'domcontentloaded'}); await p.waitForTimeout(4000);
  const campos = await p.$$('input[type=password]');
  console.log(`\n/perfil → ${campos.length} campos de contraseña`);
  const secciones = await p.evaluate(() => (document.body.innerText||'').split('\n').filter(l=>l.trim()).slice(14,30));
  console.log('  ', secciones.join(' | ').slice(0,200));
  if (campos.length >= 2) {
    console.log('\n1. Cambiar con la contraseña ACTUAL equivocada:');
    await campos[0].fill('claveIncorrecta123'); await campos[1].fill(NUEVA);
    if (campos[2]) await campos[2].fill(NUEVA);
    for (const h of await p.$$('button')) { const t=((await h.textContent())||'').trim();
      if (/cambiar|actualizar contrase/i.test(t) && await h.isVisible()) { await h.click(); break; } }
    await p.waitForTimeout(4000);
    let msg = await p.evaluate(() => (document.body.innerText||'').match(/[^\n]*(incorrect|no coincide|error|actual)[^\n]*/i));
    console.log('   →', msg ? msg[0].slice(0,110) : '(sin mensaje visible)');

    console.log('\n2. Ahora con la correcta:');
    const c2 = await p.$$('input[type=password]');
    await c2[0].fill(VIEJA); await c2[1].fill(NUEVA); if (c2[2]) await c2[2].fill(NUEVA);
    for (const h of await p.$$('button')) { const t=((await h.textContent())||'').trim();
      if (/cambiar|actualizar contrase/i.test(t) && await h.isVisible()) { await h.click(); break; } }
    await p.waitForTimeout(5000);
    msg = await p.evaluate(() => (document.body.innerText||'').match(/[^\n]*(actualiz|cambi|listo|éxito)[^\n]*/i));
    console.log('   →', msg ? msg[0].slice(0,110) : '(sin mensaje visible)');
  }
  await b.close();
})();
