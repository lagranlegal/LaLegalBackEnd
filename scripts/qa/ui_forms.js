// Reproduce el bug del 03/09 (contratos) en los formularios largos que nunca se revisaron.
// La pregunta: al enviar incompleto, ¿el usuario VE algo sin hacer scroll?
const { chromium } = require(process.env.QA_PLAYWRIGHT
  || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const PW = process.env.QA_PASSWORD || 'QaLab2026!';

const FORMS = [
  { name: 'Nueva venta',        path: '/ventas/nueva' },
  { name: 'Nuevo ingreso',      path: '/inventario/ingresos/nuevo' },
  { name: 'Nueva transformación', path: '/inventario/transformaciones/nueva' },
  { name: 'Nuevo contrato (referencia, ya arreglado)', path: '/contratos/nuevo' },
];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await page.fill('input[type=email]', 'qa.admin@qalab.com');
  await page.fill('input[type=password]', PW);
  await page.click('button[type=submit]');
  await page.waitForTimeout(6000);

  for (const f of FORMS) {
    await page.goto(BASE + f.path, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3500);
    // el botón primario de envío suele ser el último submit de la página
    const btns = await page.$$('button[type=submit], button');
    let target = null, label = '';
    for (const b of btns) {
      const t = ((await b.textContent()) || '').trim();
      if (/crear|vender|registrar|guardar|transformar|confirmar/i.test(t) && await b.isVisible()) { target = b; label = t; }
    }
    if (!target) { console.log(`\n### ${f.name}: no se encontró botón de envío`); continue; }

    await target.scrollIntoViewIfNeeded();
    const beforeY = await page.evaluate(() => window.scrollY);
    await target.click({ force: true }).catch(() => {});
    await page.waitForTimeout(2500);

    const r = await page.evaluate(() => {
      const vh = window.innerHeight;
      const visible = (el) => {
        const b = el.getBoundingClientRect();
        return b.top >= 0 && b.bottom <= vh && b.width > 0 && b.height > 0;
      };
      // mensajes de error: rojo, role=alert, aria-invalid, o texto típico
      const nodes = [...document.querySelectorAll('p,span,div,li')].filter(e => {
        const t = (e.textContent || '').trim();
        if (!t || t.length > 120 || e.children.length) return false;
        const s = getComputedStyle(e);
        const rojo = /rgb\((2[0-5]\d|1[89]\d),\s*(\d{1,2}|1[01]\d),/.test(s.color);
        return rojo || e.getAttribute('role') === 'alert';
      });
      return {
        scrollY: window.scrollY,
        mensajes: nodes.map(n => n.textContent.trim()),
        visiblesSinScroll: nodes.filter(visible).map(n => n.textContent.trim()),
        toasts: [...document.querySelectorAll('[role=status],[data-sonner-toast],.toast')].map(n => n.textContent.trim()),
        dialogos: document.querySelectorAll('[role=dialog]').length,
        focoEn: document.activeElement ? (document.activeElement.getAttribute('name') || document.activeElement.getAttribute('placeholder') || document.activeElement.tagName) : null,
      };
    });
    console.log(`\n### ${f.name}   (botón: "${label}")`);
    console.log(`  scrollY: ${beforeY} → ${r.scrollY}`);
    console.log(`  mensajes de error en el DOM : ${r.mensajes.length ? JSON.stringify(r.mensajes.slice(0,4)) : '(ninguno)'}`);
    console.log(`  VISIBLES sin scroll         : ${r.visiblesSinScroll.length ? JSON.stringify(r.visiblesSinScroll.slice(0,4)) : '(NINGUNO)'}`);
    console.log(`  toasts: ${JSON.stringify(r.toasts)} · diálogos: ${r.dialogos} · foco: ${r.focoEn}`);
  }
  await browser.close();
})();
