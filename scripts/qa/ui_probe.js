const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  for (const path of ['/ventas/nueva','/inventario/ingresos/nuevo','/inventario/transformaciones/nueva']) {
    await p.goto(BASE+path, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(4000);
    const info = await p.evaluate(() => ({
      url: location.pathname,
      botones: [...document.querySelectorAll('button')].filter(b=>b.offsetParent).map(b=>`"${(b.textContent||'').trim().slice(0,40)}"${b.disabled?' [disabled]':''}`),
      h1: (document.querySelector('h1,h2')||{}).textContent,
      texto: document.body.innerText.slice(0,200).replace(/\n+/g,' | '),
    }));
    console.log(`\n### ${path} → ${info.url}`);
    console.log('  título:', (info.h1||'').trim());
    console.log('  botones:', info.botones.join(' · ') || '(ninguno)');
  }
  await b.close();
})();
