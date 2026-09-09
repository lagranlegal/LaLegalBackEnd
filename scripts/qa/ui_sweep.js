const { chromium } = require(process.env.QA_PLAYWRIGHT || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
const RUTAS = ['/', '/contratos', '/ventas', '/inventario', '/clientes', '/caja', '/cuentas', '/reportes', '/identidad', '/auditoria', '/configuracion', '/catalogos'];

function lum(c){const[r,g,b]=c.map(v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)});return .2126*r+.7152*g+.0722*b}
function ratio(a,b){const l1=lum(a),l2=lum(b);return (Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05)}

(async () => {
  const b = await chromium.launch();
  for (const tema of ['light','dark']) {
    const ctx = await b.newContext({viewport:{width:1440,height:900}, colorScheme: tema});
    const p = await ctx.newPage();
    await p.goto(`${BASE}/auth/login`, {waitUntil:'networkidle'});
    await p.fill('input[type=email]','qa.admin@qalab.com'); await p.fill('input[type=password]', process.env.QA_PASSWORD||'QaLab2026!');
    await p.click('button[type=submit]'); await p.waitForTimeout(6000);
    const malos = new Map();
    for (const ruta of RUTAS) {
      await p.goto(BASE+ruta, {waitUntil:'domcontentloaded'}); await p.waitForTimeout(2600);
      const muestras = await p.evaluate(() => {
        const out=[]; const walk=el=>{for(const n of el.childNodes){
          if(n.nodeType===3&&n.textContent.trim().length>3){const q=n.parentElement,s=getComputedStyle(q);
            let bg='rgba(0, 0, 0, 0)',e=q; while(e&&(bg==='rgba(0, 0, 0, 0)'||bg==='transparent')){bg=getComputedStyle(e).backgroundColor;e=e.parentElement;}
            out.push({t:n.textContent.trim().slice(0,42),fg:s.color,bg,size:parseFloat(s.fontSize),w:+s.fontWeight});}
          else if(n.nodeType===1) walk(n);}};
        walk(document.body); return out;
      });
      const parse=s=>(s.match(/\d+/g)||[0,0,0]).slice(0,3).map(Number);
      for (const s of muestras) {
        const r = ratio(parse(s.fg), parse(s.bg));
        const grande = s.size>=24 || (s.size>=18.66 && s.w>=700);
        const min = grande?3:4.5;
        if (r < min) {
          const k = `${s.fg}|${s.bg}|${s.size}`;
          if (!malos.has(k)) malos.set(k, {ratio:r.toFixed(2), min, size:s.size, fg:s.fg, bg:s.bg, ej:s.t, rutas:new Set()});
          malos.get(k).rutas.add(ruta);
        }
      }
    }
    console.log(`\n=== TEMA ${tema.toUpperCase()} — ${malos.size} combinación(es) por debajo de WCAG AA ===`);
    for (const m of [...malos.values()].sort((a,b)=>a.ratio-b.ratio))
      console.log(`  ${m.ratio} (mín ${m.min})  ${m.size}px  "${m.ej}"  en ${[...m.rutas].slice(0,4).join(', ')}${m.rutas.size>4?` +${m.rutas.size-4}`:''}`);
    await ctx.close();
  }
  await b.close();
})();
