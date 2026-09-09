const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const LINK = process.argv[2], NUEVA = 'RecuperadaQA2026!';
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext({viewport:{width:1280,height:900}})).newPage();
  await p.goto(LINK, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(6000);
  const t = await p.evaluate(() => (document.body.innerText||'').split('\n').filter(x=>x.trim()).slice(0,5));
  console.log('pantalla:', t.join(' | ').slice(0,150));
  const c = await p.$$('input[type=password]');
  console.log(`campos de contraseña: ${c.length}`);
  if (!c.length) { await b.close(); return; }
  for (const x of c) await x.fill(NUEVA);
  for (const h of await p.$$('button')) { const tx=((await h.textContent())||'').trim();
    if (/guardar|cambiar|continuar/i.test(tx) && await h.isVisible()) { await h.click(); break; } }
  await p.waitForTimeout(8000);
  console.log('tras guardar →', await p.evaluate(() => location.pathname));
  await b.close();
})();
