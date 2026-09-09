const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext({viewport:{width:360,height:800}})).newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  await p.goto(BASE+'/cuentas', {waitUntil:'domcontentloaded'}); await p.waitForTimeout(4000);
  const r = await p.evaluate(() => {
    const W = document.documentElement.clientWidth;
    // subir desde el path hasta el ancestro que de verdad se sale
    const fuera = [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > W + 1);
    return fuera.slice(0, 6).map(e => {
      const b = e.getBoundingClientRect();
      return `<${e.tagName.toLowerCase()}> ${Math.round(b.width)}px hasta x=${Math.round(b.right)} · ${(e.className||'').toString().slice(0,70)} · "${(e.textContent||'').trim().slice(0,25)}"`;
    });
  });
  console.log(`viewport 360 · elementos que se salen (de fuera hacia dentro):`);
  r.forEach(x => console.log('  ' + x));
  await b.close();
})();
