const asciiArt = `
 __  __           _       _   _      _                      _      ____        _       _   _
|  \\/  | ___  ___| |__   | \\ | | ___| |___      _____  _ __| | __ / ___|  ___ | |_   _| |_(_) ___  _ __  ___
| |\\/| |/ _ \\/ __| '_ \\  |  \\| |/ _ \\ __\\ \\ /\\ / / _ \\| '__| |/ / \\___ \\ / _ \\| | | | | __| |/ _ \\| '_ \\/ __|
| |  | |  __/\\__ \\ | | | | |\\  |  __/ |_ \\ V  V / (_) | |  |   <   ___) | (_) | | |_| | |_| | (_) | | | \\__ \\
|_|  |_|\\___||___/_| |_| |_| \\_|\\___|\\__| \\_/\\_/ \\___/|_|  |_|\\_\\ |____/ \\___/|_|\\__,_|\\__|_|\\___/|_| |_|___/
`.trimEnd();

const pre = document.getElementById('ascii-logo');
const wrap = document.getElementById('ascii-wrap');

function buildLogo(){
  pre.textContent = '';
  const lines = asciiArt.split('\n');
  lines.forEach(line=>{
    const row = document.createElement('div');
    row.className = 'row';
    [...line].forEach(ch=>{
      const span = document.createElement('span');
      span.className = ch === ' ' ? 'ch space' : 'ch';
      span.textContent = ch === ' ' ? ' ' : ch;
      row.appendChild(span);
    });
    pre.appendChild(row);
  });
}
buildLogo();

const chars = Array.from(pre.querySelectorAll('.ch:not(.space)'));

function measureCenters(){
  chars.forEach(el=>{
    // Temporarily clear transform so the rect reflects the untransformed layout position.
    const t = el.style.transform;
    el.style.transform = '';
    const r = el.getBoundingClientRect();
    el._cx = r.left + r.width/2;
    el._cy = r.top + r.height/2;
    el.style.transform = t;
  });
}
chars.forEach(el=>{ el._x = 0; el._y = 0; el._vx = 0; el._vy = 0; });
measureCenters();
addEventListener('resize', measureCenters);
addEventListener('scroll', measureCenters, {passive: true});

let mouse = {x: -9999, y:-9999, active:false};
let running = false;

function start(){
  if(running) return;
  running = true;
  requestAnimationFrame(tick);
}

wrap.addEventListener('mousemove', e=>{
  mouse.x = e.clientX; mouse.y = e.clientY; mouse.active = true;
  start();
});
wrap.addEventListener('mouseleave', ()=>{ mouse.active = false; start(); });

const RADIUS = 110, FORCE = 12, RESTORE = 0.18, DAMP = 0.72;
const REST_EPS = 0.05;

function tick(){
  let moving = false;
  for(const el of chars){
    let fx = 0, fy = 0;
    if(mouse.active){
      const cx = el._cx + el._x;
      const cy = el._cy + el._y;
      const dx = cx - mouse.x;
      const dy = cy - mouse.y;
      const dist = Math.hypot(dx, dy);
      if(dist < RADIUS && dist > 0.001){
        const t = 1 - dist / RADIUS;
        const push = FORCE * t * t;
        fx += (dx / dist) * push;
        fy += (dy / dist) * push;
      }
    }
    fx += -el._x * RESTORE;
    fy += -el._y * RESTORE;
    el._vx = (el._vx + fx) * DAMP;
    el._vy = (el._vy + fy) * DAMP;
    el._x += el._vx;
    el._y += el._vy;
    if(Math.abs(el._x) < REST_EPS && Math.abs(el._y) < REST_EPS &&
       Math.abs(el._vx) < REST_EPS && Math.abs(el._vy) < REST_EPS){
      el._x = 0; el._y = 0; el._vx = 0; el._vy = 0;
    } else {
      moving = true;
    }
    el.style.transform = (el._x || el._y) ? `translate(${el._x.toFixed(2)}px, ${el._y.toFixed(2)}px)` : '';
    const d = Math.hypot(el._x, el._y);
    el.style.color = d > 1 ? '#b6ffcb' : '';
    el.style.textShadow = d > 1 ? '0 0 12px rgba(76,255,138,0.9), 0 0 24px rgba(76,255,138,0.4)' : '';
  }
  if(moving || mouse.active){
    requestAnimationFrame(tick);
  } else {
    running = false;
  }
}

document.getElementById('year').textContent = new Date().getFullYear();
