const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const CONTRATO = process.argv[2];
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1280,height:900}});
  const p = await ctx.newPage();
  await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
  await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
  await p.click('button[type=submit]'); await p.waitForTimeout(6000);
  await p.goto(`${BASE}/contratos/${CONTRATO}`, {waitUntil:'domcontentloaded'});
  await p.waitForTimeout(7000);
  // interceptar window.print para que no bloquee
  await p.evaluate(() => { window.print = () => { window.__imprimio = true; }; });
  for (const h of await p.$$('button')) {
    const t=((await h.textContent())||'').trim();
    if (/imprimir/i.test(t) && await h.isVisible()) { await h.click(); break; }
  }
  await p.waitForTimeout(2500);
  await p.emulateMedia({ media: 'print' });
  await p.waitForTimeout(800);
  const r = await p.evaluate(() => {
    const visible = [...document.querySelectorAll('body *')].filter(e => {
      const s = getComputedStyle(e);
      const b = e.getBoundingClientRect();
      return s.display !== 'none' && s.visibility !== 'hidden' && b.height > 0;
    });
    // el contenedor de impresión suele ser el que queda visible con menos ancestros
    const texto = (document.body.innerText || '').replace(/\n{3,}/g, '\n\n').trim();
    return { imprimio: !!window.__imprimio, largo: texto.length, texto: texto.slice(0, 900), visibles: visible.length };
  });
  console.log(`window.print() llamado: ${r.imprimio}`);
  console.log(`caracteres visibles en modo impresión: ${r.largo}`);
  console.log('--- lo que saldría en papel ---');
  console.log(r.texto || '(VACÍO)');
  await p.pdf({ path: 'contrato_plantilla_vacia.pdf', format: 'Letter' }).catch(e => console.log('pdf:', e.message));
  await b.close();
})();
