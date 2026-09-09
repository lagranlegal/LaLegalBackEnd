const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const RECOVERY = process.argv[2];
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1440,height:950}});
  const p = await ctx.newPage();
  // --- 1. Enlace de recuperación en navegador
  console.log('=== Enlace de recuperación, abierto en navegador ===');
  await p.goto(RECOVERY, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(6000);
  const rec = await p.evaluate(() => ({ url: location.pathname, txt: (document.body.innerText||'').split('\n').filter(x=>x.trim()).slice(0,6) }));
  console.log(`  ${rec.url} · ${rec.txt.join(' | ').slice(0,140)}`);
  console.log(`  ¿pide contraseña nueva? ${(await p.$$('input[type=password]')).length > 0}`);

  // --- 2. Panel de plataforma
  const ctx2 = await b.newContext({viewport:{width:1440,height:950}});
  const q = await ctx2.newPage();
  await q.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await q.fill('input[type=email]','mateojaras@gmail.com'); await q.fill('input[type=password]','mateo123');
  await q.click('button[type=submit]'); await q.waitForTimeout(7000);
  await q.goto(BASE+'/platform', {waitUntil:'domcontentloaded'}); await q.waitForTimeout(6000);
  const pl = await q.evaluate(() => ({
    url: location.pathname,
    filas: document.querySelectorAll('tbody tr').length,
    botones: [...document.querySelectorAll('button')].filter(b=>b.offsetParent).map(b=>(b.textContent||'').trim().slice(0,26)).filter(Boolean),
    texto: (document.body.innerText||'').split('\n').filter(x=>x.trim()).slice(0,20),
  }));
  console.log(`\n=== Panel de plataforma (${pl.url}) ===`);
  console.log(`  empresas listadas: ${pl.filas}`);
  console.log(`  botones: ${pl.botones.join(' · ')}`);
  console.log('  ' + pl.texto.slice(6,18).join(' | ').slice(0,300));
  // abrir el detalle de una empresa
  const filas = await q.$$('tbody tr');
  if (filas.length) {
    await filas[0].click(); await q.waitForTimeout(3500);
    const det = await q.evaluate(() => ({
      dialogo: document.querySelectorAll('[role=dialog]').length,
      texto: [...document.querySelectorAll('[role=dialog]')].map(d=>(d.innerText||'').split('\n').filter(x=>x.trim()).slice(0,22).join(' | ')).join(''),
    }));
    console.log(`\n  detalle de empresa (diálogos: ${det.dialogo}):`);
    console.log('  ' + det.texto.slice(0,420));
  }
  await b.close();
})();
