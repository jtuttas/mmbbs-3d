import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const VQ = '?v=6';        // Datenversion – bei neuen Daten hochzählen (Browser-Cache)
const SLAB = 0.30;        // Deckenstärke
const EYE = 1.65;
const RADIUS = 0.22;
const $ = (id) => document.getElementById(id);

const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
const maxAniso = renderer.capabilities.getMaxAnisotropy();

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xcfdbe3);
scene.fog = new THREE.Fog(0xcfdbe3, 120, 320);
const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.05, 1000);
scene.add(new THREE.HemisphereLight(0xffffff, 0xb8b4ae, 1.7));
const sun = new THREE.DirectionalLight(0xfff3e2, 1.4); sun.position.set(-40, 80, 30); scene.add(sun);
scene.add(new THREE.AmbientLight(0xffffff, 0.25));

let META, MPP, W, H, CX, CZ;
const floors = [];            // {id, level, name, group, labels, grid, imgS, texS, texL, data}
let cur = 1;                  // index in floors (EG)
let mode = 'none';

const toWorld = (px, py) => [px * MPP - CX, py * MPP - CZ];
const toPx = (x, z) => [(x + CX) / MPP, (z + CZ) / MPP];

// ---------- loading ----------
const loader = new THREE.TextureLoader();
const loadTex = (url) => new Promise((res, rej) => loader.load(url, res, undefined, rej));
const loadImg = (url) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
let done = 0, total = 1;
const tick = () => { done++; $('prog').firstElementChild.style.width = (100 * done / total) + '%'; };

async function init() {
  META = await (await fetch(`data/meta.json${VQ}`, { cache: 'no-cache' })).json();
  MPP = META.metersPerPx; W = META.width; H = META.height; CX = W * MPP / 2; CZ = H * MPP / 2;
  total = META.floors.length * 3 + 1;
  floorMat.map.repeat.set(W * MPP / 2.2, H * MPP / 2.2);
  const ground = loadTex(`data/ground.webp${VQ}`).then((t) => { tick(); return t; });
  const groundMask = loadTex(`data/ground_mask.png${VQ}`);
  await Promise.all(META.floors.map(async (f, i) => {
    const [data, texS, gridImg] = await Promise.all([
      fetch(`data/${f.id}.json${VQ}`).then((r) => r.json()).then((d) => { tick(); return d; }),
      loadTex(`data/${f.id}_floor_s.webp${VQ}`).then((t) => { tick(); return t; }),
      loadImg(`data/${f.id}_grid.png${VQ}`).then((t) => { tick(); return t; }),
    ]);
    floors[i] = { ...f, data, texS, gridImg };
  }));
  // Geschosshöhen aus den Treppenangaben der Pläne (Stufenzahl × Steigung)
  const eg = floors.findIndex((f) => f.level === 0);
  floors[eg].y0 = 0;
  for (let i = eg + 1; i < floors.length; i++) floors[i].y0 = floors[i - 1].y0 + floors[i - 1].height;
  for (let i = eg - 1; i >= 0; i--) floors[i].y0 = floors[i + 1].y0 - floors[i].height;
  for (const f of floors) f.h = f.height;
  for (const f of floors) buildFloor(f);
  buildGround(await ground, await groundMask);
  buildTrees();
  buildRoof();
  buildUI();
  $('goWalk').disabled = $('goOrbit').disabled = false;
  $('goWalk').textContent = 'Begehung starten';
  const sp = META.spawn ? toWorld(META.spawn.x - 60, META.spawn.y) : [0, 0];
  player.x = sp[0]; player.z = sp[1]; player.y = 0; player.yaw = -Math.PI / 2; player.pitch = 0; camY = EYE;
  setFloor(1, false);
  setMode('orbit');
  renderer.setAnimationLoop(loop);
}

// ---------- geometry ----------
function shapeFrom(poly) {
  const [outer, holes] = poly;
  const s = new THREE.Shape(outer.map(([x, y]) => { const [wx, wz] = toWorld(x, y); return new THREE.Vector2(wx, -wz); }));
  for (const h of holes) s.holes.push(new THREE.Path(h.map(([x, y]) => { const [wx, wz] = toWorld(x, y); return new THREE.Vector2(wx, -wz); })));
  return s;
}
function planUV(geo) {
  const p = geo.attributes.position, uv = new Float32Array(p.count * 2);
  for (let i = 0; i < p.count; i++) {
    const [px, py] = toPx(p.getX(i), p.getZ(i));
    uv[2 * i] = px / W; uv[2 * i + 1] = 1 - py / H;
  }
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
}
let showPlan = false, showFurn = true;
try { showPlan = localStorage.getItem('mmbbs3d.plan') === '1'; showFurn = localStorage.getItem('mmbbs3d.furn') !== '0'; } catch (e) {}
function floorTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 512; const x = c.getContext('2d');
  x.fillStyle = '#d9d2c5'; x.fillRect(0, 0, 512, 512);
  // Eichenparkett-artige Dielen
  const rnd = mulberry(7);
  for (let row = 0; row < 8; row++) {
    let off = (row % 2) * 128 + rnd() * 60;
    for (let col = -1; col < 4; col++) {
      const l = 72 + rnd() * 9; x.fillStyle = `hsl(33, ${24 + rnd() * 8}%, ${l}%)`;
      x.fillRect(off + col * 200, row * 64, 198, 62);
    }
  }
  for (let i = 0; i < 2500; i++) { x.fillStyle = `rgba(90,70,40,${rnd() * 0.05})`; x.fillRect(rnd() * 512, rnd() * 512, 20 + rnd() * 60, 1); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8; return t;
}
function mulberry(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const floorMat = new THREE.MeshLambertMaterial({ map: floorTexture() });
const wallMat = new THREE.MeshLambertMaterial({ color: 0xf1eee9 });
const wallMatCut = new THREE.MeshLambertMaterial({ color: 0xe2ddd5 });
const slabMat = new THREE.MeshLambertMaterial({ color: 0xf4f2ee, emissive: 0x2a2a2a });
const roofMat = new THREE.MeshLambertMaterial({ color: 0x9aa3a8 });
const facadeMat = new THREE.MeshLambertMaterial({ color: 0xc9c4bc });
const glassMat = new THREE.MeshLambertMaterial({ color: 0x9fc6d6, transparent: true, opacity: 0.28, depthWrite: false, side: THREE.DoubleSide });

function buildFloor(f) {
  const g = new THREE.Group(); const y0 = f.y0;
  const fpShapes = f.data.footprint.map(shapeFrom);
  // slab
  const slab = new THREE.ExtrudeGeometry(fpShapes, { depth: SLAB, bevelEnabled: false });
  slab.rotateX(-Math.PI / 2); slab.translate(0, y0 - SLAB, 0);
  g.add(new THREE.Mesh(slab, slabMat));
  // plan on floor
  const top = new THREE.ShapeGeometry(fpShapes); top.rotateX(-Math.PI / 2); top.translate(0, y0 + 0.004, 0); planUV(top);
  f.texS.colorSpace = THREE.SRGBColorSpace; f.texS.anisotropy = maxAniso;
  f.planMat = new THREE.MeshBasicMaterial({ map: f.texS, transparent: false, alphaTest: 0.5 });
  f.planMat.color.setScalar(0.96);
  f.planMesh = new THREE.Mesh(top, showPlan ? f.planMat : floorMat); g.add(f.planMesh);
  // walls
  const ws = f.data.walls.map(shapeFrom);
  const wg = new THREE.ExtrudeGeometry(ws, { depth: f.h - SLAB, bevelEnabled: false, curveSegments: 1 });
  wg.rotateX(-Math.PI / 2); wg.translate(0, y0, 0);
  f.wallMesh = new THREE.Mesh(wg, wallMat); g.add(f.wallMesh);
  // facade: parapet + glazing + lintel
  if (f.data.facade && f.data.facade.length) {
    const fs = f.data.facade.map(shapeFrom);
    const part = (h0, h1, mat) => {
      const gg = new THREE.ExtrudeGeometry(fs, { depth: h1 - h0, bevelEnabled: false, curveSegments: 1 });
      gg.rotateX(-Math.PI / 2); gg.translate(0, y0 + h0, 0); const m = new THREE.Mesh(gg, mat); g.add(m); return gg;
    };
    const top = f.h - SLAB;
    const pg = part(0, 0.9, facadeMat); part(0.9, top - 0.6, glassMat); const lg = part(top - 0.6, top, facadeMat);
    f.facadeEdges = [pg, lg];
  }
  // dark edge lines on wall tops for readability in overview
  const eg = new THREE.EdgesGeometry(wg, 30);
  f.edges = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: 0x6d6a66, transparent: true, opacity: 0.35 }));
  g.add(f.edges);
  // labels
  f.labels = new THREE.Group();
  for (const r of f.data.rooms) {
    if (r.cluster) continue;
    const [x, z] = toWorld(r.x, r.y);
    const sp = makeLabel(r); sp.position.set(x, y0 + 2.45, z); sp.userData = r; f.labels.add(sp);
  }
  g.add(f.labels);
  // collision grid
  const gc = document.createElement('canvas'); gc.width = f.gridImg.width; gc.height = f.gridImg.height;
  const cx = gc.getContext('2d'); cx.drawImage(f.gridImg, 0, 0);
  const px = cx.getImageData(0, 0, gc.width, gc.height).data;
  f.grid = new Uint8Array(gc.width * gc.height);
  for (let i = 0; i < f.grid.length; i++) { const v = px[i * 4]; f.grid[i] = v > 150 ? 2 : v > 75 ? 1 : v > 25 ? 3 : 0; }
  f.gw = gc.width; f.gh = gc.height; f.cell = f.data.grid.cell;
  f.group = g; scene.add(g);
  buildStairs(f);
  buildFurniture(f); buildPlants(f);
}

function makeLabel(r) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 150;
  const x = c.getContext('2d');
  x.fillStyle = 'rgba(16,22,27,.82)'; roundRect(x, 4, 4, 504, 142, 18); x.fill();
  x.fillStyle = '#ff6a3d'; x.font = '600 40px "IBM Plex Mono", monospace'; x.textAlign = 'center';
  x.fillText(r.id, 256, 52);
  x.fillStyle = '#e9eef1'; x.font = '500 38px "IBM Plex Sans", sans-serif';
  let name = r.name || ''; while (x.measureText(name).width > 480 && name.length > 4) name = name.slice(0, -2);
  if (name !== (r.name || '')) name += '…';
  x.fillText(name, 256, 96);
  x.fillStyle = '#93a1ab'; x.font = '400 28px "IBM Plex Sans", sans-serif'; x.fillText(r.ngf || '', 256, 134);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, transparent: true, depthWrite: false }));
  s.scale.set(1.7, 0.5, 1); s.renderOrder = 5;
  return s;
}
function roundRect(x, a, b, w, h, r) { x.beginPath(); x.moveTo(a + r, b); x.arcTo(a + w, b, a + w, b + h, r); x.arcTo(a + w, b + h, a, b + h, r); x.arcTo(a, b + h, a, b, r); x.arcTo(a, b, a + w, b, r); x.closePath(); }

function paveTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 512; const x = c.getContext('2d');
  x.fillStyle = '#8f8d88'; x.fillRect(0, 0, 512, 512);
  const rnd = mulberry(21);
  // Betonsteinpflaster 30 × 60 cm im Läuferverband (512 px = 3 m)
  const pw = 102, ph = 51;
  for (let r = 0; r < 512 / ph + 1; r++) {
    const off = (r % 2) * pw / 2;
    for (let cIdx = -1; cIdx < 512 / pw + 1; cIdx++) {
      const l = 66 + rnd() * 10, sat = 3 + rnd() * 4;
      x.fillStyle = `hsl(${35 + rnd() * 10}, ${sat}%, ${l}%)`;
      x.fillRect(off + cIdx * pw + 2, r * ph + 2, pw - 4, ph - 4);
    }
  }
  for (let i = 0; i < 6000; i++) { x.fillStyle = `rgba(${rnd() < 0.5 ? '255,255,255' : '40,40,40'},${rnd() * 0.07})`; x.fillRect(rnd() * 512, rnd() * 512, 2, 2); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}
let groundPlanMat, groundPaveMat;
function buildGround(tex, mask) {
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = maxAniso;
  const sizeX = W * MPP, sizeZ = H * MPP;
  const pave = paveTexture(); pave.repeat.set(sizeX / 3, sizeZ / 3);
  groundPlanMat = new THREE.MeshBasicMaterial({ map: tex, alphaTest: 0.5, color: 0xdedede });
  groundPaveMat = new THREE.MeshLambertMaterial({ map: pave, alphaMap: mask, alphaTest: 0.5 });
  const pg = new THREE.PlaneGeometry(sizeX, sizeZ); pg.rotateX(-Math.PI / 2);
  const m = new THREE.Mesh(pg, showPlan ? groundPlanMat : groundPaveMat);
  m.position.y = 0.002; scene.add(m);
  // Umgebung: Pflasterband, dahinter Rasen
  const ring = (w0, mat, y) => {
    const B = w0;
    const parts = [[0, -(sizeZ / 2 + B / 2), B * 2 + sizeX, B], [0, sizeZ / 2 + B / 2, B * 2 + sizeX, B],
      [-(sizeX / 2 + B / 2), 0, B, sizeZ], [sizeX / 2 + B / 2, 0, B, sizeZ]];
    for (const [x, z, w, h] of parts) {
      const p = new THREE.PlaneGeometry(w, h); p.rotateX(-Math.PI / 2);
      const uv = p.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * w / 3, uv.getY(i) * h / 3);
      const mm = new THREE.Mesh(p, mat); mm.position.set(x, y, z); scene.add(mm);
    }
  };
  const pave2 = paveTexture(); pave2.repeat.set(1, 1);
  ring(14, new THREE.MeshLambertMaterial({ map: pave2 }), -0.01);
  const grass = new THREE.MeshLambertMaterial({ color: 0xa9b98f });
  const B = 400, o = 14;
  for (const [x, z, w, h] of [[0, -(sizeZ / 2 + o + B / 2), B * 2 + sizeX + 2 * o, B], [0, sizeZ / 2 + o + B / 2, B * 2 + sizeX + 2 * o, B],
    [-(sizeX / 2 + o + B / 2), 0, B, sizeZ + 2 * o], [sizeX / 2 + o + B / 2, 0, B, sizeZ + 2 * o]]) {
    const p = new THREE.PlaneGeometry(w, h); p.rotateX(-Math.PI / 2); const mm = new THREE.Mesh(p, grass); mm.position.set(x, -0.03, z); scene.add(mm);
  }
  // Parkhaus südlich des Gebäudes
  const pk = new THREE.Mesh(new THREE.BoxGeometry(sizeX * 0.98, 12, 14), new THREE.MeshLambertMaterial({ color: 0x8c9196 }));
  pk.position.set(0, 6, sizeZ / 2 + 7.4); scene.add(pk);
  ground = m;
}
function buildTrees() {
  const trees = (META.trees || []).slice();
  // ergänzende Bäume am Platzrand
  const sizeX = W * MPP, sizeZ = H * MPP;
  for (let i = 0; i < 7; i++) trees.push([null, null, 2.6, -sizeX / 2 - 7, -sizeZ / 2 + 4 + i * (sizeZ - 8) / 6]);
  for (let i = 0; i < 8; i++) trees.push([null, null, 2.6, -sizeX / 2 + 2 + i * (sizeX - 4) / 7, -sizeZ / 2 - 7]);
  const rnd = mulberry(5);
  const trunkG = new THREE.CylinderGeometry(0.16, 0.24, 1, 8); trunkG.translate(0, 0.5, 0);
  const crownG = new THREE.IcosahedronGeometry(1, 1);
  const mT = inst(trunkG, new THREE.MeshLambertMaterial({ color: 0x6b5843 }), trees.length);
  const mC = inst(crownG, new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true }), trees.length * 6);
  trees.forEach((t, i) => {
    let x, z; if (t[0] === null) { x = t[3]; z = t[4]; } else [x, z] = toWorld(t[0], t[1]);
    const r = Math.max(1.8, t[2]), hT = 2.2 + r * 0.55;
    put(mT, i, x, 0, z, 0, 1 + r * 0.12, hT, 1 + r * 0.12);
    for (let b = 0; b < 6; b++) {
      const a = rnd() * Math.PI * 2, d = b ? r * 0.45 : 0, s = r * (b ? 0.55 + rnd() * 0.2 : 0.75);
      put(mC, i * 6 + b, x + Math.cos(a) * d, hT + r * 0.35 + (b ? (rnd() - 0.3) * r * 0.5 : r * 0.2), z + Math.sin(a) * d, rnd() * 6, s, s * 0.85, s);
      mC.setColorAt(i * 6 + b, LEAF_COLORS[Math.floor(rnd() * LEAF_COLORS.length)]);
    }
  });
  mC.instanceColor.needsUpdate = true;
  scene.add(mT, mC);
}
let ground, roof;
function buildRoof() {
  const top = floors[floors.length - 1];
  const geo = new THREE.ExtrudeGeometry(top.data.footprint.map(shapeFrom), { depth: SLAB, bevelEnabled: false });
  geo.rotateX(-Math.PI / 2); geo.translate(0, top.y0 + top.h - SLAB, 0);
  roof = new THREE.Mesh(geo, roofMat); scene.add(roof);
}

// ---------- Innenausstattung ----------
const M_WOOD = new THREE.MeshLambertMaterial({ color: 0xc9a77c });
const M_METAL = new THREE.MeshLambertMaterial({ color: 0x3a3f44 });
const M_CAB = new THREE.MeshLambertMaterial({ color: 0xf3f1ec });
const M_CHAIR = new THREE.MeshLambertMaterial({ color: 0xffffff });
const M_POT = new THREE.MeshLambertMaterial({ color: 0x4a4f55 });
const M_LEAF = new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true });
const CHAIR_COLORS = [0x2fb6c9, 0xff6a3d, 0x3d4a57, 0x8bc34a, 0xf2b134].map((c) => new THREE.Color(c));
const LEAF_COLORS = [0x3f7d3a, 0x4f9a43, 0x2f6b3a, 0x5c8f2f].map((c) => new THREE.Color(c));

const GEO = (() => {
  const box = (w, h, d, x, y, z) => { const g = new THREE.BoxGeometry(w, h, d); g.translate(x, y, z); return g; };
  const chairShell = mergeGeometries([box(0.44, 0.05, 0.42, 0, 0.46, 0), box(0.44, 0.42, 0.04, 0, 0.7, 0.2)]);
  const chairLegs = mergeGeometries([box(0.03, 0.45, 0.03, -0.19, 0.225, -0.17), box(0.03, 0.45, 0.03, 0.19, 0.225, -0.17),
    box(0.03, 0.45, 0.03, -0.19, 0.225, 0.17), box(0.03, 0.45, 0.03, 0.19, 0.225, 0.17)]);
  const top = box(1, 0.035, 1, 0, 0.735, 0);
  const leg = box(0.04, 0.72, 0.04, 0, 0.36, 0);
  const roundTop = new THREE.CylinderGeometry(0.5, 0.5, 0.035, 28); roundTop.translate(0, 0.735, 0);
  const roundLeg = mergeGeometries([new THREE.CylinderGeometry(0.035, 0.035, 0.72, 10).translate(0, 0.36, 0), new THREE.CylinderGeometry(0.25, 0.25, 0.02, 20).translate(0, 0.01, 0)]);
  const cab = box(1, 1, 1, 0, 0.5, 0);
  const pot = new THREE.CylinderGeometry(0.2, 0.16, 0.42, 16); pot.translate(0, 0.21, 0);
  const leaf = new THREE.IcosahedronGeometry(0.3, 1);
  return { chairShell, chairLegs, top, leg, roundTop, roundLeg, cab, pot, leaf };
})();

function inst(geo, mat, n) { const m = new THREE.InstancedMesh(geo, mat, Math.max(1, n)); m.count = n; return m; }
const _o = new THREE.Object3D();
function put(mesh, i, x, y, z, ry, sx = 1, sy = 1, sz = 1) {
  _o.position.set(x, y, z); _o.rotation.set(0, ry, 0); _o.scale.set(sx, sy, sz); _o.updateMatrix(); mesh.setMatrixAt(i, _o.matrix);
}

function buildFurniture(f) {
  const list = f.data.furn || [];
  const y0 = f.y0, grp = new THREE.Group();
  const tables = list.filter((a) => a[0] === 'table'), chairs = list.filter((a) => a[0] === 'chair');
  const rounds = list.filter((a) => a[0] === 'round'), cabs = list.filter((a) => a[0] === 'cab');
  // Tische
  const mTop = inst(GEO.top, M_WOOD, tables.length), mLeg = inst(GEO.leg, M_METAL, tables.length * 4);
  tables.forEach(([, px, py, w, h, a], i) => {
    const [x, z] = toWorld(px, py), ry = -a * Math.PI / 180;
    put(mTop, i, x, y0, z, ry, w, 1, h);
    const c = Math.cos(ry), s = Math.sin(ry), dx = w / 2 - 0.06, dz = h / 2 - 0.06;
    [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sz], k) => {
      const lx = sx * dx, lz = sz * dz;
      put(mLeg, i * 4 + k, x + lx * c + lz * s, y0, z - lx * s + lz * c, ry);
    });
  });
  // runde Tische
  const mRT = inst(GEO.roundTop, M_WOOD, rounds.length), mRL = inst(GEO.roundLeg, M_METAL, rounds.length);
  rounds.forEach(([, px, py, w, h], i) => { const [x, z] = toWorld(px, py); const r = (w + h) / 2; put(mRT, i, x, y0, z, 0, r, 1, r); put(mRL, i, x, y0, z, 0); });
  // Einbaumöbel / Schränke
  const mCab = inst(GEO.cab, M_CAB, cabs.length);
  cabs.forEach(([, px, py, w, h, a], i) => { const [x, z] = toWorld(px, py); put(mCab, i, x, y0, z, -a * Math.PI / 180, w - 0.02, 0.92, h - 0.02); });
  // Stühle – zum nächsten Tisch gedreht
  const tW = tables.map(([, px, py]) => toWorld(px, py)).concat(rounds.map(([, px, py]) => toWorld(px, py)));
  const mShell = inst(GEO.chairShell, M_CHAIR, chairs.length), mCL = inst(GEO.chairLegs, M_METAL, chairs.length);
  chairs.forEach(([, px, py, w, h, a], i) => {
    const [x, z] = toWorld(px, py);
    let best = null, bd = 1.3;
    for (const [tx, tz] of tW) { const d = Math.hypot(tx - x, tz - z); if (d < bd) { bd = d; best = [tx, tz]; } }
    let ry = -a * Math.PI / 180;
    if (best) ry = Math.atan2(-(best[0] - x), -(best[1] - z));
    put(mShell, i, x, y0, z, ry); put(mCL, i, x, y0, z, ry);
    const ci = Math.abs(Math.floor(px / 300) * 7 + Math.floor(py / 300) * 13 + f.level * 3) % CHAIR_COLORS.length;
    mShell.setColorAt(i, CHAIR_COLORS[ci]);
  });
  if (chairs.length) mShell.instanceColor.needsUpdate = true;
  for (const m of [mTop, mLeg, mRT, mRL, mCab, mShell, mCL]) { m.instanceMatrix.needsUpdate = true; m.frustumCulled = false; grp.add(m); }
  f.furnPts = list.map(([, px, py]) => toWorld(px, py));
  f.furnGroup = grp; grp.visible = showFurn; f.group.add(grp);
}

function buildPlants(f) {
  const skip = /WC|Technik|Treppen|Aufzug|PuMi|Lager|Abstell|Kühl|Frost|Putz|HAR|ELT|Schacht|Server|Dusch|Umkleide|Müll/i;
  const spots = [];
  const occupied = (x, z) => f.furnPts.some(([fx, fz]) => Math.hypot(fx - x, fz - z) < 0.8) || spots.some(([sx, sz]) => Math.hypot(sx - x, sz - z) < 2.5);
  const nearWall = (x, z) => { for (let k = 0; k < 8; k++) { const a = k * Math.PI / 4; if (cellVal(f, x + Math.cos(a) * 0.45, z + Math.sin(a) * 0.45) === 2) return true; } return false; };
  const clear = (x, z) => { for (let k = 0; k < 9; k++) { const a = k * Math.PI / 4, r = k === 8 ? 0 : 0.28; if (cellVal(f, x + Math.cos(a) * r, z + Math.sin(a) * r) !== 1) return false; } return true; };
  for (const r of f.data.rooms) {
    if (r.cluster || skip.test(r.name || '')) continue;
    const want = /Flur|Aula|Cafeteria|Foyer|Halle|Lernlandschaft/i.test(r.name || '') ? 3 : 1;
    const [cx, cz] = toWorld(r.x, r.y); let got = 0;
    for (let rad = 0.5; rad < 9 && got < want; rad += 0.35) {
      const n = Math.ceil(rad * 10);
      for (let k = 0; k < n && got < want; k++) {
        const a = k / n * Math.PI * 2 + rad, x = cx + Math.cos(a) * rad, z = cz + Math.sin(a) * rad;
        if (clear(x, z) && nearWall(x, z) && !occupied(x, z) && lineFree(f, r.x, r.y, ...toPx(x, z))) { spots.push([x, z]); got++; }
      }
    }
  }
  const rnd = mulberry(100 + f.level);
  const BLOBS = 5;
  const mPot = inst(GEO.pot, M_POT, spots.length), mLeaf = inst(GEO.leaf, M_LEAF, spots.length * BLOBS);
  spots.forEach(([x, z], i) => {
    const tall = rnd() < 0.5, s = 0.8 + rnd() * 0.5;
    put(mPot, i, x, f.y0, z, rnd() * 6, s, s, s);
    for (let b = 0; b < BLOBS; b++) {
      const h = (tall ? 0.7 + b * 0.28 : 0.55 + b * 0.12) * s, rr = (tall ? 0.18 : 0.25) * s;
      const a = rnd() * Math.PI * 2, sc = (tall ? 0.9 - b * 0.08 : 1.1 - b * 0.1) * s;
      put(mLeaf, i * BLOBS + b, x + Math.cos(a) * rr * (b ? 1 : 0.3), f.y0 + h, z + Math.sin(a) * rr * (b ? 1 : 0.3), rnd() * 6, sc, sc * (tall ? 1.3 : 0.9), sc);
      mLeaf.setColorAt(i * BLOBS + b, LEAF_COLORS[Math.floor(rnd() * LEAF_COLORS.length)]);
    }
  });
  if (spots.length) mLeaf.instanceColor.needsUpdate = true;
  for (const m of [mPot, mLeaf]) { m.instanceMatrix.needsUpdate = true; m.frustumCulled = false; f.furnGroup.add(m); }
}

function setPlan(v) {
  showPlan = v; try { localStorage.setItem('mmbbs3d.plan', v ? '1' : '0'); } catch (e) {}
  for (const f of floors) f.planMesh.material = v ? f.planMat : floorMat;
  if (ground) ground.material = v ? groundPlanMat : groundPaveMat;
  $('tPlan').classList.toggle('on', v);
}
function setFurn(v) {
  showFurn = v; try { localStorage.setItem('mmbbs3d.furn', v ? '1' : '0'); } catch (e) {}
  for (const f of floors) f.furnGroup.visible = v;
  $('tFurn').classList.toggle('on', v);
}

// ---------- floors / visibility ----------
let cutLevel = 6;
function applyVisibility() {
  for (const f of floors) {
    if (mode === 'walk') {
      f.group.visible = true; f.labels.visible = f === floors[cur]; f.edges.visible = false;
    } else {
      f.group.visible = f.level <= cutLevel; f.labels.visible = f.level === Math.min(cutLevel, 5); f.edges.visible = true;
    }
  }
  roof.visible = mode === 'walk' || cutLevel >= 6;
}
function floorUI() {
  const f = floors[cur];
  document.querySelectorAll('#floors button').forEach((b) => b.classList.toggle('on', +b.dataset.i === cur));
  $('miniF').textContent = f.name;
}
// Geschosswechsel durch Laufen über die Treppe
function floorChangedByWalking(i) {
  const prev = floors[cur]; cur = i; const f = floors[cur];
  if (prev.texL && prev.texL !== 'loading') { prev.planMat.map = prev.texS; prev.planMat.needsUpdate = true; }
  if (!f.texL) {
    f.texL = 'loading';
    loadTex(`data/${f.id}_floor.webp${VQ}`).then((t) => { t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = maxAniso; f.texL = t; if (floors[cur] === f) { f.planMat.map = t; f.planMat.needsUpdate = true; } });
  } else if (f.texL !== 'loading') { f.planMat.map = f.texL; f.planMat.needsUpdate = true; }
  floorUI(); applyVisibility(); drawMini(true); lastRoom = undefined;
}
function setFloor(i, keepPos = true) {
  i = Math.max(0, Math.min(floors.length - 1, i));
  const prev = floors[cur]; cur = i; const f = floors[cur];
  // high-res plan texture for the floor you stand on
  if (prev && prev !== f && prev.texL) prev.planMat.map = prev.texS, prev.planMat.needsUpdate = true;
  if (!f.texL) {
    f.texL = 'loading';
    loadTex(`data/${f.id}_floor.webp${VQ}`).then((t) => {
      t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = maxAniso; f.texL = t;
      if (floors[cur] === f && mode === 'walk') { f.planMat.map = t; f.planMat.needsUpdate = true; }
    });
  } else if (f.texL !== 'loading' && mode === 'walk') { f.planMat.map = f.texL; f.planMat.needsUpdate = true; }
  if (keepPos && blocked(player.x, player.z)) {
    // über das nächstgelegene Treppenhaus ins Geschoss
    let best = null, bd = 1e9;
    for (const s of f.data.stairs) {
      const [sx, sz] = toWorld(s.x, s.y), d = Math.hypot(sx - player.x, sz - player.z);
      if (d < bd) { bd = d; best = [sx, sz]; }
    }
    const p = best ? nearestFree(best[0], best[1]) : nearestFree(player.x, player.z);
    if (p) { player.x = p[0]; player.z = p[1]; }
  }
  player.y = f.y0; camY = f.y0 + EYE;
  floorUI();
  if (mode === 'orbit') { cutLevel = f.level; $('cutR').value = cutLevel; updateCutLabel(); }
  applyVisibility(); drawMini(true);
}

// ---------- Treppen ----------
const stairMat = new THREE.MeshLambertMaterial({ color: 0xd8d4cc });
const stairEdgeMat = new THREE.LineBasicMaterial({ color: 0x8f8a82 });
function buildStairs(f) {
  f.steps = [];
  const geos = [];
  for (const st of f.data.stairs3d || []) {
    const pts = st.p.map(([x, y]) => toWorld(x, y));
    const cpts = (st.pc || st.p).map(([x, y]) => toWorld(x, y));
    let minx = 1e9, maxx = -1e9, minz = 1e9, maxz = -1e9;
    for (const [x, z] of cpts) { minx = Math.min(minx, x); maxx = Math.max(maxx, x); minz = Math.min(minz, z); maxz = Math.max(maxz, z); }
    f.steps.push({ pts: cpts, h: st.h, bb: [minx, maxx, minz, maxz], landing: !!st.landing });
    const shape = new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, -z)));
    const th = st.landing ? 0.3 : 0.32;
    const g = new THREE.ExtrudeGeometry(shape, { depth: th, bevelEnabled: false });
    g.rotateX(-Math.PI / 2); g.translate(0, f.y0 + st.h - th, 0);
    geos.push(g);
  }
  if (!geos.length) return;
  const merged = mergeGeometries(geos);
  f.group.add(new THREE.Mesh(merged, stairMat));
  f.group.add(new THREE.LineSegments(new THREE.EdgesGeometry(merged, 20), stairEdgeMat));
}
function inPoly(pts, x, z) {
  let c = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, zi] = pts[i], [xj, zj] = pts[j];
    if (((zi > z) !== (zj > z)) && (x < (xj - xi) * (z - zi) / (zj - zi) + xi)) c = !c;
  }
  return c;
}
function polyDist(pts, x, z) {
  let d = 1e9;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [x1, z1] = pts[j], [x2, z2] = pts[i], dx = x2 - x1, dz = z2 - z1, L = dx * dx + dz * dz || 1;
    const t = Math.max(0, Math.min(1, ((x - x1) * dx + (z - z1) * dz) / L));
    d = Math.min(d, Math.hypot(x - x1 - t * dx, z - z1 - t * dz));
  }
  return d;
}
function floorAt(y) {
  let i = 0;
  for (let k = 0; k < floors.length; k++) if (floors[k].y0 <= y + 0.3) i = k;
  return i;
}
// Oberfläche unter (x,z) nahe der aktuellen Höhe py – Boden, Stufe oder Podest
function surfaceAt(x, z, py) {
  const fi = floorAt(py); let best = null, bd = 0.46;
  for (let k = Math.max(0, fi - 1); k <= Math.min(floors.length - 1, fi + 1); k++) {
    const f = floors[k];
    let onStep = false;
    for (const s of f.steps) {
      if (x < s.bb[0] - 0.3 || x > s.bb[1] + 0.3 || z < s.bb[2] - 0.3 || z > s.bb[3] + 0.3) continue;
      const inside = inPoly(s.pts, x, z);
      if (inside) onStep = true;
      const y = f.y0 + s.h; if (Math.abs(y - py) >= bd) continue;
      // kleine Lücken zwischen Wendelstufen/Podesten überbrücken
      if (inside || polyDist(s.pts, x, z) < 0.28) { bd = Math.abs(y - py); best = y; }
    }
    const v = cellVal(f, x, z);
    if (!onStep && (v === 1 || (v === 0 && f.level === 0)) && Math.abs(f.y0 - py) < bd) { bd = Math.abs(f.y0 - py); best = f.y0; }
  }
  return best;
}
function wallHit(fi, x, z) {
  const f = floors[fi];
  for (let a = 0; a < 8; a++) {
    const ang = a * Math.PI / 4, v = cellVal(f, x + Math.cos(ang) * RADIUS, z + Math.sin(ang) * RADIUS);
    if (v === 2 || v === -1) return true;
  }
  return false;
}
// Bewegung prüfen: liefert neue Fußhöhe oder null
function tryMove(x, z, py) {
  const y = surfaceAt(x, z, py);
  if (y === null) return null;
  if (wallHit(floorAt(y), x, z)) return null;
  return y;
}

// ---------- collision ----------
function cellVal(f, x, z) {
  const [px, py] = toPx(x, z);
  const gx = Math.floor(px * MPP / f.cell), gy = Math.floor(py * MPP / f.cell);
  if (gx < 0 || gy < 0 || gx >= f.gw || gy >= f.gh) return -1;
  return f.grid[gy * f.gw + gx];
}
function blocked(x, z) {
  const f = floors[cur];
  const c = cellVal(f, x, z); if (c === 3) return true;
  for (let a = 0; a < 9; a++) {
    const r = a === 8 ? 0 : RADIUS, ang = a * Math.PI / 4;
    const v = cellVal(f, x + Math.cos(ang) * r, z + Math.sin(ang) * r);
    if (v === 2 || v === -1) return true;
    if (v === 0 && f.level !== 0) return true;   // außerhalb des Gebäudes nur im EG (Außenanlage)
  }
  return false;
}
function nearestFree(x, z) {
  for (let r = 0.2; r < 25; r += 0.2) {
    const n = Math.ceil(r * 12);
    for (let k = 0; k < n; k++) {
      const a = k / n * Math.PI * 2, nx = x + Math.cos(a) * r, nz = z + Math.sin(a) * r;
      if (!blocked(nx, nz) && cellVal(floors[cur], nx, nz) === 1) return [nx, nz];
    }
  }
  return null;
}

// ---------- player / input ----------
const player = { x: 0, z: 0, y: 0, yaw: 0, pitch: 0 };
let camY = 1.65;
const keys = {};
let locked = false, dragging = false, lastX = 0, lastY = 0;
const joy = { active: false, id: null, x: 0, y: 0, cx: 0, cy: 0 }, look = { id: null, x: 0, y: 0 };

addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT') return;
  keys[e.code] = true;
  if (e.code === 'KeyM') setMode(mode === 'walk' ? 'orbit' : 'walk');
  if (e.code === 'KeyP') setPlan(!showPlan);
  if (e.code === 'KeyO') setFurn(!showFurn);
  if (e.code === 'KeyE' || e.code === 'PageUp') { setFloor(cur + 1); e.preventDefault(); }
  if (e.code === 'KeyQ' || e.code === 'PageDown') { setFloor(cur - 1); e.preventDefault(); }
});
addEventListener('keyup', (e) => { keys[e.code] = false; });
canvas.addEventListener('click', () => { if (mode === 'walk' && !matchMedia('(pointer:coarse)').matches) canvas.requestPointerLock?.(); });
document.addEventListener('pointerlockchange', () => { locked = document.pointerLockElement === canvas; $('cross').style.display = locked ? 'block' : 'none'; });
document.addEventListener('mousemove', (e) => {
  if (mode !== 'walk') return;
  if (locked) turn(e.movementX, e.movementY);
  else if (dragging) { turn(e.clientX - lastX, e.clientY - lastY); lastX = e.clientX; lastY = e.clientY; }
});
canvas.addEventListener('mousedown', (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY; });
addEventListener('mouseup', () => { dragging = false; });
function turn(dx, dy) {
  player.yaw -= dx * 0.0025; player.pitch = Math.max(-1.35, Math.min(1.35, player.pitch - dy * 0.0025));
}
// touch: left joystick, right look
canvas.addEventListener('touchstart', (e) => {
  if (mode !== 'walk') return;
  for (const t of e.changedTouches) {
    if (t.clientX < innerWidth * 0.45 && joy.id === null) {
      joy.id = t.identifier; joy.cx = t.clientX; joy.cy = t.clientY; joy.x = joy.y = 0;
      const j = $('joy'); j.style.left = (t.clientX - 60) + 'px'; j.style.top = (t.clientY - 60) + 'px'; j.style.bottom = 'auto';
    } else if (look.id === null) { look.id = t.identifier; look.x = t.clientX; look.y = t.clientY; }
  }
  e.preventDefault();
}, { passive: false });
canvas.addEventListener('touchmove', (e) => {
  for (const t of e.changedTouches) {
    if (t.identifier === joy.id) {
      let dx = t.clientX - joy.cx, dy = t.clientY - joy.cy; const l = Math.hypot(dx, dy);
      if (l > 50) { dx *= 50 / l; dy *= 50 / l; }
      joy.x = dx / 50; joy.y = dy / 50; $('joy').firstElementChild.style.transform = `translate(${dx}px,${dy}px)`;
    } else if (t.identifier === look.id) { turn((t.clientX - look.x) * 1.6, (t.clientY - look.y) * 1.6); look.x = t.clientX; look.y = t.clientY; }
  }
  e.preventDefault();
}, { passive: false });
canvas.addEventListener('touchend', (e) => {
  for (const t of e.changedTouches) {
    if (t.identifier === joy.id) { joy.id = null; joy.x = joy.y = 0; $('joy').firstElementChild.style.transform = ''; }
    if (t.identifier === look.id) look.id = null;
  }
});

// ---------- modes ----------
const orbit = new OrbitControls(camera, canvas);
orbit.enableDamping = true; orbit.maxPolarAngle = Math.PI * 0.495; orbit.minDistance = 5; orbit.maxDistance = 220;
function setMode(m) {
  mode = m;
  $('mWalk').classList.toggle('on', m === 'walk'); $('mOrbit').classList.toggle('on', m === 'orbit');
  $('cut').style.display = m === 'orbit' ? 'block' : 'none';
  $('room').style.display = m === 'walk' ? 'block' : 'none';
  $('joy').style.display = m === 'walk' && matchMedia('(pointer:coarse)').matches ? 'block' : 'none';
  orbit.enabled = m === 'orbit';
  if (m === 'orbit') {
    if (document.pointerLockElement) document.exitPointerLock();
    const f = floors[cur];
    if (f.texL && f.texL !== 'loading') { f.planMat.map = f.texS; f.planMat.needsUpdate = true; }
    orbit.target.set(player.x * 0.3, Math.max(0, floors[Math.max(0, Math.min(floors.length - 1, cutLevel + 1))].y0) * 0.5, player.z * 0.3);
    camera.position.set(-62, 58, -58);
    scene.fog.near = 200; scene.fog.far = 600;
  } else {
    scene.fog.near = 120; scene.fog.far = 320;
    const f = floors[cur];
    if (f.texL && f.texL !== 'loading') { f.planMat.map = f.texL; f.planMat.needsUpdate = true; }
    if (Math.abs(player.y - floors[cur].y0) > 0.01 && floorAt(player.y) !== cur) player.y = floors[cur].y0;
    if (surfaceAt(player.x, player.z, player.y) === null) { player.y = floors[cur].y0; const p = nearestFree(player.x, player.z); if (p) { player.x = p[0]; player.z = p[1]; } }
    camY = player.y + EYE;
  }
  applyVisibility(); drawMini(true);
}
function updateCutLabel() {
  const f = floors.find((x) => x.level === cutLevel);
  $('cutV').textContent = cutLevel >= 6 ? 'Dach' : f ? f.id : '';
}

// ---------- UI ----------
function buildUI() {
  const box = $('floors');
  [...floors].map((f, i) => [f, i]).reverse().forEach(([f, i]) => {
    const b = document.createElement('button'); b.textContent = f.id; b.dataset.i = i; b.title = f.name;
    b.onclick = () => setFloor(i); box.appendChild(b);
  });
  $('mWalk').onclick = () => setMode('walk');
  $('mOrbit').onclick = () => setMode('orbit');
  $('tPlan').onclick = () => setPlan(!showPlan); $('tFurn').onclick = () => setFurn(!showFurn);
  setPlan(showPlan); setFurn(showFurn);
  $('mInfo').onclick = () => { const i = $('info'); i.style.display = i.style.display === 'block' ? 'none' : 'block'; };
  $('goWalk').onclick = () => { $('start').style.display = 'none'; setMode('walk'); };
  $('goOrbit').onclick = () => { $('start').style.display = 'none'; setMode('orbit'); };
  $('cutR').oninput = (e) => {
    cutLevel = +e.target.value; updateCutLabel();
    const i = floors.findIndex((f) => f.level === Math.min(cutLevel, 5));
    if (i >= 0 && i !== cur) { cur = i; document.querySelectorAll('#floors button').forEach((b) => b.classList.toggle('on', +b.dataset.i === cur)); $('miniF').textContent = floors[cur].name; drawMini(true); }
    applyVisibility();
  };
  $('miniC').addEventListener('click', (e) => {
    const r = e.target.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width * W, py = (e.clientY - r.top) / r.height * H;
    const [x, z] = toWorld(px, py);
    player.x = x; player.z = z;
    if (blocked(x, z)) { const p = nearestFree(x, z); if (p) { player.x = p[0]; player.z = p[1]; } }
    player.y = floors[cur].y0; camY = player.y + EYE;
    if (mode !== 'walk') { $('start').style.display = 'none'; setMode('walk'); }
  });
}

// minimap
const mini = $('miniC'), mctx = mini.getContext('2d');
let miniBg = null, miniFloor = -1;
function drawMini(force) {
  if (!floors[cur]) return;
  if (force || miniFloor !== cur) {
    const img = floors[cur].texS.image; miniFloor = cur;
    miniBg = img;
  }
  mctx.clearRect(0, 0, mini.width, mini.height);
  mctx.fillStyle = '#1b2329'; mctx.fillRect(0, 0, mini.width, mini.height);
  if (miniBg) mctx.drawImage(miniBg, 0, 0, mini.width, mini.height);
  if (mode === 'walk') {
    const [px, py] = toPx(player.x, player.z);
    const sx = px / W * mini.width, sy = py / H * mini.height;
    const dx = -Math.sin(player.yaw), dz = -Math.cos(player.yaw);
    mctx.save(); mctx.translate(sx, sy); mctx.rotate(Math.atan2(dz, dx));
    mctx.fillStyle = 'rgba(255,106,61,.25)'; mctx.beginPath(); mctx.moveTo(0, 0); mctx.arc(0, 0, 22, -0.6, 0.6); mctx.fill();
    mctx.fillStyle = '#ff6a3d'; mctx.beginPath(); mctx.moveTo(7, 0); mctx.lineTo(-5, -5); mctx.lineTo(-5, 5); mctx.fill();
    mctx.restore();
  }
}

// ---------- room HUD ----------
let lastRoom;
function updateRoom() {
  const f = floors[cur]; let best = null, bd = 1e9;
  const [px, py] = toPx(player.x, player.z);
  for (const r of f.data.rooms) {
    if (r.cluster) continue;
    const d = Math.hypot(r.x - px, r.y - py) * MPP;
    if (d < bd && d < 7 && lineFree(f, px, py, r.x, r.y)) { bd = d; best = r; }
  }
  if (best !== lastRoom) {
    lastRoom = best;
    $('rId').textContent = best ? best.id : f.id;
    $('rName').textContent = best ? (best.name || '') : 'Verkehrsfläche';
    $('rNgf').textContent = best ? best.ngf : f.name;
  }
  // stairs hint
  let nearStair = false;
  for (const s of f.data.stairs) if (Math.hypot(s.x - px, s.y - py) * MPP < 6) nearStair = true;
  const h = $('hint');
  if (nearStair) { h.style.display = 'block'; h.textContent = 'Treppenhaus · einfach die Treppe hinauf- oder hinunterlaufen (Q / E springt direkt)'; }
  else h.style.display = 'none';
}
function lineFree(f, x0, y0, x1, y1) {
  const n = Math.ceil(Math.hypot(x1 - x0, y1 - y0) * MPP / 0.1);
  for (let i = 1; i < n; i++) {
    const [x, z] = toWorld(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n);
    if (cellVal(f, x, z) === 2) return false;
  }
  return true;
}

// ---------- loop ----------
const clock = new THREE.Clock();
let frame = 0;
function loop() {
  const dt = Math.min(clock.getDelta(), 0.05);
  if (mode === 'walk') {
    let fw = 0, st = 0;
    if (keys.KeyW || keys.ArrowUp) fw += 1; if (keys.KeyS || keys.ArrowDown) fw -= 1;
    if (keys.KeyD) st += 1; if (keys.KeyA) st -= 1;
    if (keys.ArrowLeft) player.yaw += 1.8 * dt; if (keys.ArrowRight) player.yaw -= 1.8 * dt;
    fw -= joy.y; st += joy.x;
    const sp = (keys.ShiftLeft || keys.ShiftRight ? 5.5 : 2.6) * dt;
    const l = Math.hypot(fw, st);
    if (l > 0.05) {
      const k = sp / Math.max(1, l);
      const sx = -Math.sin(player.yaw), sz = -Math.cos(player.yaw);
      const dx = (sx * fw + Math.cos(player.yaw) * st) * k, dz = (sz * fw - Math.sin(player.yaw) * st) * k;
      let y = tryMove(player.x + dx, player.z, player.y);
      if (y !== null) { player.x += dx; player.y = y; }
      y = tryMove(player.x, player.z + dz, player.y);
      if (y !== null) { player.z += dz; player.y = y; }
      const fi = floorAt(player.y);
      if (fi !== cur) floorChangedByWalking(fi);
    }
    camY += (player.y + EYE - camY) * Math.min(1, dt * 12);
    camera.position.set(player.x, camY, player.z);
    camera.rotation.set(player.pitch, player.yaw, 0, 'YXZ');
    if (frame % 6 === 0) { updateRoom(); }
    drawMini();
  } else {
    orbit.update();
    if (frame % 30 === 0) drawMini();
  }
  frame++;
  renderer.render(scene, camera);
}
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight);
});
init().catch((e) => { $('goWalk').textContent = 'Fehler beim Laden'; console.error(e); });
