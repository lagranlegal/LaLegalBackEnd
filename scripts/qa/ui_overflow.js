const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:360,height:800}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  for (const ruta of ['/caja','/cuentas','/contratos','/inventario']) {
    await p.goto(BASE+ruta, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(2500);
    const r = await p.evaluate(() => {
      const de = document.documentElement, W = de.clientWidth;
      const culpables = [...document.querySelectorAll('body *')].map(e=>{
        const b = e.getBoundingClientRect();
        if (b.width<=0 || b.right <= W+1 || getComputedStyle(e).position==='fixed') return null;
        // el culpable real es el más profundo que se sale
        const hijoSeSale = [...e.children].some(c=>c.getBoundingClientRect().right > W+1);
        if (hijoSeSale) return null;
        return { tag:e.tagName.toLowerCase(), cls:(e.className||'').toString().slice(0,60),
                 texto:(e.textContent||'').trim().slice(0,40), right:Math.round(b.right), ancho:Math.round(b.width) };
      }).filter(Boolean);
      return { W, scrollW: de.scrollWidth, culpables: culpables.slice(0,5) };
    });
    console.log(`\n### ${ruta}  (viewport ${r.W}px, contenido ${r.scrollW}px → desborda ${r.scrollW-r.W}px)`);
    for (const c of r.culpables) console.log(`  <${c.tag}> ancho ${c.ancho}px, llega a x=${c.right}  "${c.texto}"  .${c.cls}`);
  }
  await b.close();
})();
