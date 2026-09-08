// Playwright no es dependencia del proyecto: se resuelve desde el caché de npx
// (ver ESTADO.md, "Trampas del entorno"). Se puede apuntar a otra copia con QA_PLAYWRIGHT.
const { chromium } = require(process.env.QA_PLAYWRIGHT
  || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';

const ACTORS = [
  { role: 'Admin',     email: 'qa.admin@qalab.com' },
  { role: 'Asesor',    email: 'qa.asesor@qalab.com' },
  { role: 'Bodega',    email: 'qa.bodega@qalab.com' },
];
const PW = process.env.QA_PASSWORD || (process.env.QA_PASSWORD || 'QaLab2026!');

(async () => {
  const browser = await chromium.launch();
  for (const a of ACTORS) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 120)); });
    await page.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
    await page.fill('input[type=email]', a.email);
    await page.fill('input[type=password]', PW);
    await page.click('button[type=submit]');
    await page.waitForURL(u => !u.pathname.startsWith('/auth'), { timeout: 45000 }).catch(()=>{});
    await page.waitForTimeout(3000);
    const menu = await page.$$eval('nav a, aside a', els =>
      els.map(e => (e.textContent || '').trim()).filter(Boolean));
    console.log(`\n### ${a.role}  (${page.url().replace(BASE,'')})`);
    console.log('  menú:', [...new Set(menu)].join(' · ') || '(vacío)');
    // rutas directas por URL
    for (const path of ['/contratos','/inventario','/caja','/identidad','/auditoria','/reportes','/cuentas','/configuracion','/ventas','/clientes','/catalogos','/platform']) {
      await page.goto(BASE + path, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1200);
      const final = page.url().replace(BASE,"").split("?")[0];
      console.log(`  ${path.padEnd(16)} → ${final === path ? 'ENTRA' : 'redirige a ' + final}`);
    }
    if (errors.length) console.log('  errores de consola:', errors.slice(0,3).join(' | '));
    await ctx.close();
  }
  await browser.close();
})();
