// Playwright no es dependencia del proyecto: se resuelve desde el caché de npx
// (ver ESTADO.md, "Trampas del entorno"). Se puede apuntar a otra copia con QA_PLAYWRIGHT.
const { chromium } = require(process.env.QA_PLAYWRIGHT
  || `${process.env.HOME}/.npm/_npx/e41f203b7505f1fb/node_modules/playwright`);
const BASE = process.env.QA_FRONT_URL || 'https://la-legal-front-end.vercel.app';
function lum(c){const [r,g,b]=c.map(v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)});return 0.2126*r+0.7152*g+0.0722*b}
function ratio(a,b){const l1=lum(a),l2=lum(b);return ((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05)).toFixed(2)}
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport:{width:1440,height:900} });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/auth/login`, { waitUntil:'networkidle' });
  await page.fill('input[type=email]','qa.asesor@qalab.com');
  await page.fill('input[type=password]',(process.env.QA_PASSWORD || 'QaLab2026!'));
  await page.click('button[type=submit]');
  await page.waitForTimeout(6000);
  // contraste de todo texto visible
  const samples = await page.evaluate(() => {
    const out=[];
    const walk=(el)=>{
      for(const n of el.childNodes){
        if(n.nodeType===3 && n.textContent.trim().length>3){
          const p=n.parentElement, s=getComputedStyle(p);
          let bg='rgba(0, 0, 0, 0)', e=p;
          while(e && (bg==='rgba(0, 0, 0, 0)'||bg==='transparent')){ bg=getComputedStyle(e).backgroundColor; e=e.parentElement; }
          out.push({t:n.textContent.trim().slice(0,45), fg:s.color, bg, size:s.fontSize, weight:s.fontWeight});
        } else if(n.nodeType===1) walk(n);
      }
    };
    walk(document.body);
    return out;
  });
  const parse=s=>(s.match(/\d+/g)||[0,0,0]).slice(0,3).map(Number);
  const seen=new Set(); const bad=[];
  for(const s of samples){
    const key=s.fg+s.bg+s.size;
    if(seen.has(key)) continue; seen.add(key);
    const r=parseFloat(ratio(parse(s.fg),parse(s.bg)));
    const px=parseFloat(s.size); const large = px>=24 || (px>=18.66 && +s.weight>=700);
    const min = large?3:4.5;
    if(r<min) bad.push({...s, ratio:r, min});
  }
  console.log('=== Textos por debajo del contraste WCAG AA ===');
  if(!bad.length) console.log('  ninguno');
  for(const b of bad) console.log(`  ${b.ratio} (mín ${b.min})  ${b.size} ${b.weight}  "${b.t}"  fg=${b.fg} bg=${b.bg}`);
  // responsive 360
  await page.setViewportSize({width:360,height:740});
  await page.waitForTimeout(1500);
  const ov = await page.evaluate(()=>({scrollW:document.documentElement.scrollWidth, clientW:document.documentElement.clientWidth}));
  console.log(`\n=== 360px: scrollWidth=${ov.scrollW} clientWidth=${ov.clientW} → ${ov.scrollW>ov.clientW?'DESBORDA HORIZONTALMENTE':'ok'}`);
  await page.screenshot({path:'mobile_360.png', fullPage:true});
  await browser.close();
})();
