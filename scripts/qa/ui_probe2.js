const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  for (const ruta of process.argv.slice(2)) {
    await p.goto(BASE+ruta, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(6000);
    const r = await p.evaluate(() => ({
      botones: [...document.querySelectorAll('button')].filter(b=>b.offsetParent).map(b=>`"${(b.textContent||'').trim().slice(0,32)}"${b.disabled?'[dis]':''}`),
      titulo: (document.querySelector('h1,h2')||{}).textContent,
      filas: document.querySelectorAll('tbody tr').length,
    }));
    console.log(`\n### ${ruta} — «${(r.titulo||'').trim()}» · ${r.filas} filas`);
    console.log('  ', r.botones.filter(x=>x!=='""').join(' · '));
  }
  await b.close();
})();
