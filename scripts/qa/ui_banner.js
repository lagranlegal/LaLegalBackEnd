const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(7000);
  const banner = await p.evaluate(() => {
    const t = document.body.innerText;
    const m = t.match(/Caja[^\n]{0,140}/g);
    return m ? m.slice(0,3) : [];
  });
  console.log('Banner global (la caja lleva abierta desde AYER):');
  banner.forEach(l => console.log('  ' + l));
  await p.goto(BASE+'/caja', {waitUntil:'domcontentloaded'}); await p.waitForTimeout(5000);
  const caja = await p.evaluate(() => (document.body.innerText||'').split('\n').filter(l=>l.trim()).slice(0,26));
  console.log('\nPantalla de Caja:');
  caja.forEach(l => console.log('  ' + l));
  await p.screenshot({path:'caja_ayer.png', fullPage:false});
  await b.close();
})();
