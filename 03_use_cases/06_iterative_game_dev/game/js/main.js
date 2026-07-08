import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const canvas = document.getElementById('c');
const speedEl = document.getElementById('speed');
const lapEl = document.getElementById('lap');

const renderer = new THREE.WebGLRenderer({canvas, antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.NoToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
window._DBG = { get camera(){ return camera }, get kart(){ return kart }, get yaw(){ return yaw } };
scene.fog = null;

const camera = new THREE.PerspectiveCamera(70, innerWidth/innerHeight, 0.1, 2000);

// lights
scene.add(new THREE.AmbientLight(0xffffff, 0.9));

// starfield
{
  const count = 4000;
  const pos = new Float32Array(count*3);
  for (let i=0;i<count;i++){
    const r = 600 + Math.random()*600;
    const theta = Math.random()*Math.PI*2;
    const phi = Math.acos(2*Math.random()-1);
    pos[i*3]   = r*Math.sin(phi)*Math.cos(theta);
    pos[i*3+1] = r*Math.cos(phi)*0.5;
    pos[i*3+2] = r*Math.sin(phi)*Math.sin(theta);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos,3));
  const m = new THREE.PointsMaterial({color:0xffffff,size:1.2, sizeAttenuation:true});
  scene.add(new THREE.Points(g,m));
}

// SUN
const SUN_RADIUS = 28;
const sunGroup = new THREE.Group();
scene.add(sunGroup);

const sunGeo = new THREE.SphereGeometry(SUN_RADIUS, 80, 80);
const sunMat = new THREE.ShaderMaterial({
  uniforms: { time: {value:0} },
  vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
  fragmentShader: `
    varying vec2 vUv; uniform float time;
    float hash(vec2 p){ return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453); }
    float noise(vec2 p){ vec2 i=floor(p),f=fract(p); float a=hash(i),b=hash(i+vec2(1.,0.)),c=hash(i+vec2(0.,1.)),d=hash(i+vec2(1.,1.)); vec2 u=f*f*(3.-2.*f); return mix(mix(a,b,u.x),mix(c,d,u.x),u.y); }
    float fbm(vec2 p){ float v=0.,a=0.5; for(int i=0;i<6;i++){ v+=a*noise(p); p*=2.07; a*=0.5; } return v; }
    void main(){
      vec2 uv = vUv*3.5;
      float n1 = fbm(uv + vec2(time*0.22, time*0.13));
      float n2 = fbm(uv*2.3 - vec2(time*0.31, time*0.18));
      float n = n1*0.65 + n2*0.35;
      vec3 hot  = vec3(1.0, 1.0, 0.92);
      vec3 mid  = vec3(1.0, 0.62, 0.08);
      vec3 deep = vec3(0.9, 0.12, 0.0);
      vec3 col = mix(deep, mid, smoothstep(0.25, 0.55, n));
      col = mix(col, hot, smoothstep(0.6, 0.85, n));
      col *= 1.15;
      gl_FragColor = vec4(col, 1.0);
    }
  `
});
const sun = new THREE.Mesh(sunGeo, sunMat);
sunGroup.add(sun);

const coronaMat = new THREE.MeshBasicMaterial({color:0xffb84d, transparent:true, opacity:0.35, side:THREE.BackSide, blending:THREE.AdditiveBlending});
const corona = new THREE.Mesh(new THREE.SphereGeometry(SUN_RADIUS*1.35, 48, 48), coronaMat);
sunGroup.add(corona);
const corona2 = new THREE.Mesh(new THREE.SphereGeometry(SUN_RADIUS*1.75, 48, 48), new THREE.MeshBasicMaterial({color:0xff8c2a, transparent:true, opacity:0.14, side:THREE.BackSide, blending:THREE.AdditiveBlending}));
sunGroup.add(corona2);

const sunLight = new THREE.PointLight(0xffe8c0, 12000, 900, 1.6);
sunLight.position.set(0,0,0);
scene.add(sunLight);

// sun particles – embers/solar flares
const PCOUNT = 400;
const pPos = new Float32Array(PCOUNT*3);
const pCol = new Float32Array(PCOUNT*3);
const pSize = new Float32Array(PCOUNT);
const pVel = [];
for(let i=0;i<PCOUNT;i++){
  const i3=i*3;
  const theta=Math.random()*Math.PI*2, phi=Math.acos(2*Math.random()-1);
  const r=SUN_RADIUS*0.92;
  pPos[i3]=r*Math.sin(phi)*Math.cos(theta);
  pPos[i3+1]=r*Math.sin(phi)*Math.sin(theta)*0.6 + (Math.random()-0.5)*2;
  pPos[i3+2]=r*Math.cos(phi);
  const outward = new THREE.Vector3(pPos[i3],pPos[i3+1],pPos[i3+2]).normalize();
  const speed = 2 + Math.random()*6;
  pVel.push(outward.multiplyScalar(speed));
  pVel[i].y += (Math.random()-0.5)*1.5;
  const t = Math.random();
  if(t<0.3){ pCol[i3]=1; pCol[i3+1]=1; pCol[i3+2]=0.95; }
  else if(t<0.7){ pCol[i3]=1; pCol[i3+1]=0.75; pCol[i3+2]=0.15; }
  else { pCol[i3]=1; pCol[i3+1]=0.35; pCol[i3+2]=0.05; }
  pSize[i]=1.5+Math.random()*3;
}
const pGeo = new THREE.BufferGeometry();
pGeo.setAttribute('position', new THREE.BufferAttribute(pPos,3));
pGeo.setAttribute('color', new THREE.BufferAttribute(pCol,3));
pGeo.setAttribute('size', new THREE.BufferAttribute(pSize,1));
const pMat = new THREE.PointsMaterial({size:3, vertexColors:true, transparent:true, opacity:0.9, blending:THREE.AdditiveBlending, sizeAttenuation:true, depthWrite:false});
const sunParticles = new THREE.Points(pGeo, pMat);
sunGroup.add(sunParticles);

// TRACK – interesting closed circuit orbiting the sun
const TRACK_WIDTH = 12;
const TRACK_RADIUS = 120; // average

// define spline control points that make a fun circuit around origin
const CTL = [];
const R = TRACK_RADIUS;
function addCtl(ax,az){ CTL.push(new THREE.Vector3(ax*R, 0, az*R)); }
// start / finish straight on +X side
addCtl( 1.0,  0.15);
addCtl( 1.05, 0.55);
addCtl( 0.75, 0.95);  // sweeping right-hander
addCtl( 0.2,  1.1);   // top straight
addCtl(-0.4,  0.9);
addCtl(-0.85, 0.5);   // tight left hairpin approach
addCtl(-1.1,  0.0);   // hairpin apex outer
addCtl(-0.8, -0.5);   // exit hairpin
addCtl(-0.25,-0.85);  // chicane entry
addCtl( 0.1, -0.6);
addCtl( 0.35,-0.9);   // chicane exit
addCtl( 0.75,-0.7);
addCtl( 1.1, -0.3);   // long sweeping left back to start
addCtl( 1.15, 0.0);

const trackSpline = new THREE.CatmullRomCurve3(CTL, true, 'catmullrom', 0.5);
const SEGMENTS = 600;
const splinePts = trackSpline.getPoints(SEGMENTS);
const splineTans = [];
for(let i=0;i<=SEGMENTS;i++){
  const t = i/SEGMENTS;
  splineTans.push(trackSpline.getTangent(t).normalize());
}
// compute approximate length
let trackLen = 0;
for(let i=0;i<SEGMENTS;i++) trackLen += splinePts[i].distanceTo(splinePts[i+1]);

function trackPos(t){
  const idx = Math.floor(t*SEGMENTS) % SEGMENTS;
  const frac = t*SEGMENTS - Math.floor(t*SEGMENTS);
  const a = splinePts[idx], b = splinePts[(idx+1)%SEGMENTS];
  return a.clone().lerp(b, frac);
}
function trackTangent(t){
  const idx = Math.min(Math.floor(t*SEGMENTS), SEGMENTS-1);
  return splineTans[idx].clone();
}

const STRIPS = 220;
const STRIP_GAP = 0.35;
const trackGeo = new THREE.BufferGeometry();
const verts = []; const indices = []; const colors = [];
let vi = 0;
for(let s=0;s<STRIPS;s++){
  const t0 = s/STRIPS;
  const t1 = (s + 1 - STRIP_GAP)/STRIPS;
  const hue = t0;
  const c = new THREE.Color().setHSL(hue, 1, 0.55);
  c.convertSRGBToLinear();
  const p0 = trackPos(t0), tang0 = trackTangent(t0), r0 = new THREE.Vector3(tang0.z,0,-tang0.x).normalize();
  const p1 = trackPos(t1), tang1 = trackTangent(t1), r1 = new THREE.Vector3(tang1.z,0,-tang1.x).normalize();
  const l0 = p0.clone().addScaledVector(r0, -TRACK_WIDTH/2);
  const rgt0 = p0.clone().addScaledVector(r0, TRACK_WIDTH/2);
  const l1 = p1.clone().addScaledVector(r1, -TRACK_WIDTH/2);
  const rgt1 = p1.clone().addScaledVector(r1, TRACK_WIDTH/2);
  verts.push(l0.x,l0.y,l0.z, rgt0.x,rgt0.y,rgt0.z, l1.x,l1.y,l1.z, rgt1.x,rgt1.y,rgt1.z);
  for(let k=0;k<4;k++) colors.push(c.r,c.g,c.b);
  indices.push(vi,vi+2,vi+1, vi+1,vi+2,vi+3);
  vi += 4;
}
trackGeo.setAttribute('position', new THREE.Float32BufferAttribute(verts,3));
trackGeo.setAttribute('color', new THREE.Float32BufferAttribute(colors,3));
trackGeo.setIndex(indices);
const trackMat = new THREE.MeshBasicMaterial({vertexColors:true, side:THREE.DoubleSide});
const trackMesh = new THREE.Mesh(trackGeo, trackMat);
scene.add(trackMesh);

function makeBarrier(offset){
  const pts = [];
  const N = 400;
  for(let i=0;i<=N;i++){
    const t=(i/N)%1;
    const p = trackPos(t);
    const tang = trackTangent(t);
    const right = new THREE.Vector3(tang.z,0,-tang.x).normalize();
    pts.push(p.clone().addScaledVector(right, offset));
  }
  const shape = new THREE.CatmullRomCurve3(pts, true);
  const tube = new THREE.TubeGeometry(shape, 350, 0.55, 10, true);
  return new THREE.Mesh(tube, new THREE.MeshStandardMaterial({color:0xdddddd, metalness:0.3, roughness:0.6}));
}
scene.add(makeBarrier(TRACK_WIDTH/2 + 0.5));
scene.add(makeBarrier(-TRACK_WIDTH/2 - 0.5));

// KART
const kart = new THREE.Group();
scene.add(kart);

let kartModelLoaded = false;
new GLTFLoader().load(
  '../assets/car-kit/Models/GLB format/kart-oobi.glb',
  gltf=>{
    const m = gltf.scene;
    m.rotation.y = 0;
    m.scale.setScalar(1.4);
    m.traverse(o=>{ if(o.isMesh){ o.castShadow=true; o.receiveShadow=true; }});
    kart.add(m);
    kartModelLoaded = true;
  },
  undefined,
  ()=>{ // fallback box
    const box = new THREE.Mesh(
      new THREE.BoxGeometry(1.6,0.6,2.4),
      new THREE.MeshStandardMaterial({color:0x49d0ff})
    );
    box.position.y = 0.3;
    kart.add(box);
  }
);

// physics state – free-body arcade vehicle in XZ plane
const _spawnP = trackPos(0);
const _spawnT = trackTangent(0);
let px = _spawnP.x;
let pz = _spawnP.z;
let vx = 0, vz = 0;
let heading = Math.atan2(_spawnT.x, _spawnT.z);
let lap = 0;
let lastT = 0;

  let wideShot = false;
let camYaw = heading;

const _tmpV = new THREE.Vector3();

// set initial kart position so camera sees it on frame 1
kart.position.set(px, 0.55, pz);
kart.rotation.y = heading;
{
  const bx = Math.sin(heading);
  const bz = Math.cos(heading);
  camera.position.set(px - bx*7, 3, pz - bz*7);
  camera.lookAt(px + bx*12, 0.9, pz + bz*12);
}
const INPUT = {up:false,down:false,left:false,right:false};
addEventListener('keydown', e=>{
  if(['ArrowUp','w','W'].includes(e.key)) INPUT.up=true;
  if(['ArrowDown','s','S'].includes(e.key)) INPUT.down=true;
  if(['ArrowLeft','a','A'].includes(e.key)) INPUT.left=true;
  if(['ArrowRight','d','D'].includes(e.key)) INPUT.right=true;
  if(e.key==='v' || e.key==='V') wideShot = !wideShot;
});
addEventListener('keyup', e=>{
  if(['ArrowUp','w','W'].includes(e.key)) INPUT.up=false;
  if(['ArrowDown','s','S'].includes(e.key)) INPUT.down=false;
  if(['ArrowLeft','a','A'].includes(e.key)) INPUT.left=false;
  if(['ArrowRight','d','D'].includes(e.key)) INPUT.right=false;
});

let prevTime = performance.now()/1000;
function animate(){
  requestAnimationFrame(animate);
  const now = performance.now()/1000;
  const dt = Math.min(now-prevTime, 1/30);
  prevTime = now;

  sunMat.uniforms.time.value = now;
  sun.rotation.y += dt*0.06;
  coronaMat.opacity = 0.3 + Math.sin(now*2.7)*0.08;
  corona2.material.opacity = 0.12 + Math.cos(now*1.9)*0.04;
  // animate sun particles outward
  const pos = sunParticles.geometry.attributes.position.array;
  const siz = sunParticles.geometry.attributes.size.array;
  for(let i=0;i<PCOUNT;i++){
    const i3=i*3;
    pos[i3] += pVel[i].x*dt;
    pos[i3+1] += pVel[i].y*dt;
    pos[i3+2] += pVel[i].z*dt;
    siz[i] *= 1 - dt*0.6;
    const dist = Math.sqrt(pos[i3]**2 + pos[i3+1]**2 + pos[i3+2]**2);
    if(dist > SUN_RADIUS*3.2 || siz[i]<0.2){
      const theta=Math.random()*Math.PI*2, phi=Math.acos(2*Math.random()-1);
      const r=SUN_RADIUS*0.92;
      pos[i3]=r*Math.sin(phi)*Math.cos(theta);
      pos[i3+1]=r*Math.sin(phi)*Math.sin(theta)*0.5;
      pos[i3+2]=r*Math.cos(phi);
      const out = new THREE.Vector3(pos[i3],pos[i3+1],pos[i3+2]).normalize();
      pVel[i].copy(out.multiplyScalar(2+Math.random()*6));
      pVel[i].y += (Math.random()-0.5)*1.5;
      siz[i]=1.5+Math.random()*3;
    }
  }
  sunParticles.geometry.attributes.position.needsUpdate=true;
  sunParticles.geometry.attributes.size.needsUpdate=true;

  // ------- FREE-BODY ARCADE VEHICLE -------
  const MAX_SPEED = 42;
  const ACCEL = 34;
  const BRAKE = 48;
  const COAST_DRAG = 0.55;
  const BASE_TURN_RATE = 2.8;

  const steer = (INPUT.left?1:0) + (INPUT.right?-1:0);

  // forward unit vector from heading
  const fx = Math.sin(heading);
  const fz = Math.cos(heading);
  // right unit vector
  const rx = Math.cos(heading);
  const rz = -Math.sin(heading);

  // project velocity onto heading frame
  let vFwd = vx*fx + vz*fz;   // forward component
  let vLat = vx*rx + vz*rz;   // lateral component

  const speedAbs = Math.sqrt(vx*vx + vz*vz);
  const speedRatio = Math.min(speedAbs / MAX_SPEED, 1);

  // throttle / brake along heading
  if (INPUT.up)   vFwd += ACCEL * dt;
  if (INPUT.down) vFwd -= BRAKE * dt;

  // coast drag on forward component when no throttle
  if (!INPUT.up && !INPUT.down) {
    vFwd *= Math.max(0, 1 - COAST_DRAG*dt);
  }

  vFwd = THREE.MathUtils.clamp(vFwd, -MAX_SPEED*0.45, MAX_SPEED);

  // steering – turn rate scales with speed, no turning when stopped
  const turnScale = THREE.MathUtils.clamp(speedAbs / 10, 0, 1);
  const turnDir = vFwd >= 0 ? 1 : -1;
  heading += steer * BASE_TURN_RATE * turnScale * dt * turnDir;

  const baseGrip = 42;
  const highSpeedGripDrop = Math.pow(speedRatio, 2.0) * 38;
  const grip = Math.max(baseGrip - highSpeedGripDrop, 2.8);
  vLat *= Math.max(0, 1 - grip * dt);

  // rolling resistance on forward
  vFwd *= Math.max(0, 1 - 0.25*dt);

  // recompose world velocity
  vx = fx * vFwd + rx * vLat;
  vz = fz * vFwd + rz * vLat;

  // invisible soft walls at track edges — clamp position, preserve speed
  {
    let best = 1e9, bi = 0;
    for (let i = 0; i < SEGMENTS; i += 4) {
      const dx = px - splinePts[i].x, dz = pz - splinePts[i].z;
      const d2 = dx*dx + dz*dz;
      if (d2 < best) { best = d2; bi = i; }
    }
    const cx = splinePts[bi].x, cz = splinePts[bi].z;
    const dx = cx - px, dz = cz - pz;
    const distOff = Math.sqrt(dx*dx + dz*dz);
    const halfW = TRACK_WIDTH/2 - 0.8;
    if (distOff > halfW && distOff > 0.001) {
      const nx = dx/distOff, nz = dz/distOff;
      // snap back to edge
      px = cx - nx * halfW;
      pz = cz - nz * halfW;
    }
  }

  // integrate position
  px += vx * dt;
  pz += vz * dt;

  // place kart mesh
  kart.position.set(px, 0.55, pz);
  kart.rotation.y = heading;
  kart.rotation.z = steer * speedRatio * 0.08;
  kart.rotation.x = vFwd * 0.0006;

  // speed display
  speedEl.textContent = Math.round(Math.abs(vFwd)*3.6);

  // expose for debug / measurement
  if (!window._VEH) window._VEH = {};
  window._VEH.heading = heading;
  window._VEH.vx = vx; window._VEH.vz = vz;
  window._VEH.vFwd = vFwd; window._VEH.vLat = vLat;
  window._VEH.speedAbs = speedAbs;
  window._VEH.slipAngle = Math.atan2(vLat, Math.abs(vFwd)+0.001);

  // lap counter via closest point on track
  {
    let best = 1e9, bestI = 0;
    for (let i = 0; i < SEGMENTS; i += 8) {
      const dx = px - splinePts[i].x, dz = pz - splinePts[i].z;
      const d2 = dx*dx + dz*dz;
      if (d2 < best) { best = d2; bestI = i; }
    }
    const t = bestI / SEGMENTS;
    if (lastT > 0.8 && t < 0.2 && vFwd > 1) { lap++; lapEl.textContent = lap; }
    if (lastT < 0.2 && t > 0.8 && vFwd < -1) { lap = Math.max(0, lap-1); lapEl.textContent = lap; }
    lastT = t;
  }

  // ------- CAMERA -------
  if (wideShot) {
    camera.position.set(0, 280, 0);
    camera.lookAt(0,0,0);
  } else {
    const sr = speedRatio;
    const desiredCamYaw = heading;
    let dy = desiredCamYaw - camYaw;
    dy = Math.atan2(Math.sin(dy), Math.cos(dy));
    camYaw += dy * (1 - Math.exp(-10*dt));

    _tmpV.set(0,0,-1).applyAxisAngle(new THREE.Vector3(0,1,0), camYaw);
    const dist = 7.0;
    const ht = 3.8;
    const camPos = kart.position.clone().addScaledVector(_tmpV, dist);
    camPos.y = ht;
    camera.position.lerp(camPos, 1 - Math.exp(-12*dt));

    // look slightly ahead of kart along nose, kart sits in lower-middle of frame
    const noseX = Math.sin(heading), noseZ = Math.cos(heading);
    const lookAt = kart.position.clone();
    lookAt.x += noseX * 4;
    lookAt.z += noseZ * 4;
    lookAt.y = 0.3;
    camera.lookAt(lookAt);
  }

  renderer.render(scene, camera);
}
animate();

addEventListener('resize', ()=>{
  camera.aspect = innerWidth/innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
