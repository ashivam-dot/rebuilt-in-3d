// The 3D stage: one baked scene per story, rendered frame by frame at exact times by render.py.
import * as THREE from 'three';

const S = await (await fetch('scene/scene.json')).json();
const W = 1080, H = 1920, EX = S.exaggeration, G = S.grid, R = S.radius;
const raw = new Float32Array(await (await fetch('scene/pos.bin')).arrayBuffer());
const smooth = (a, b, t) => { const u = Math.min(1, Math.max(0, (t - a) / (b - a))); return u * u * (3 - 2 * u); };
const shot = (name) => S.shots.find((s) => s.name === name);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// Terrain height (km, true scale) at a point, bilinear on the grid.
function heightAt(x, z) {
  const c = Math.min(G.cols - 1.001, Math.max(0, ((x - G.xmin) / (G.xmax - G.xmin)) * (G.cols - 1)));
  const r = Math.min(G.rows - 1.001, Math.max(0, ((z - G.zmin) / (G.zmax - G.zmin)) * (G.rows - 1)));
  const c0 = Math.floor(c), r0 = Math.floor(r), fc = c - c0, fr = r - r0;
  const h = (rr, cc) => raw[(rr * G.cols + cc) * 3 + 1];
  return (h(r0, c0) * (1 - fc) + h(r0, c0 + 1) * fc) * (1 - fr) + (h(r0 + 1, c0) * (1 - fc) + h(r0 + 1, c0 + 1) * fc) * fr;
}

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H);
renderer.setClearColor(0x000000, 0);
renderer.localClippingEnabled = true;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.insertBefore(renderer.domElement, document.getElementById('labels'));
const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0x0e1c2f, R * 4.5, R * 9);
const camera = new THREE.PerspectiveCamera(42, W / H, R * 0.01, R * 30);
scene.add(new THREE.HemisphereLight(0xdfe9f5, 0x2a3442, 1.25));
const sun = new THREE.DirectionalLight(0xfff1dc, 2.1);
sun.position.set(-R, R * 1.6, R * 0.8);
scene.add(sun);

const cut = new THREE.Plane(new THREE.Vector3(0, 0, -1), G.zmax + 1);
const loader = new THREE.TextureLoader();
const [tex, mmiTex] = await Promise.all([loader.loadAsync('scene/texture.jpg'), loader.loadAsync('scene/mmi.png')]);
tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
mmiTex.colorSpace = THREE.SRGBColorSpace; mmiTex.anisotropy = 8;

// Terrain surface.
const n = G.cols * G.rows, pos = new Float32Array(n * 3), uv = new Float32Array(n * 2), idx = [];
for (let i = 0; i < n; i++) {
  pos[i * 3] = raw[i * 3]; pos[i * 3 + 1] = raw[i * 3 + 1] * EX; pos[i * 3 + 2] = raw[i * 3 + 2];
  uv[i * 2] = (i % G.cols) / (G.cols - 1); uv[i * 2 + 1] = 1 - Math.floor(i / G.cols) / (G.rows - 1);
}
for (let r = 0; r < G.rows - 1; r++) for (let c = 0; c < G.cols - 1; c++) {
  const a = r * G.cols + c, b = a + 1, d = a + G.cols, e = d + 1;
  idx.push(a, d, b, b, d, e);
}
const terrainGeo = new THREE.BufferGeometry();
terrainGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
terrainGeo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
terrainGeo.setIndex(idx);
terrainGeo.computeVertexNormals();
scene.add(new THREE.Mesh(terrainGeo, new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0, clippingPlanes: [cut] })));
const mmiMat = new THREE.MeshBasicMaterial({ map: mmiTex, transparent: true, opacity: 0, depthWrite: false, polygonOffset: true,
  polygonOffsetFactor: -4, polygonOffsetUnits: -4, clippingPlanes: [cut] });
scene.add(new THREE.Mesh(terrainGeo, mmiMat));

// Diorama walls: rock below the surface, water above the sea floor.
const SLAB = S.slab_km * EX;
const rockTop = new THREE.Color(0x8a6d4f), rockBottom = new THREE.Color(0x2b2019);
function wall(points) {
  const rock = [], rockCol = [], water = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [x0, z0] = points[i], [x1, z1] = points[i + 1];
    const h0 = heightAt(x0, z0) * EX, h1 = heightAt(x1, z1) * EX;
    rock.push(x0, h0, z0, x0, -SLAB, z0, x1, h1, z1, x1, h1, z1, x0, -SLAB, z0, x1, -SLAB, z1);
    for (const y of [h0, -SLAB, h1, h1, -SLAB, -SLAB]) {
      const c = rockBottom.clone().lerp(rockTop, (y + SLAB) / (SLAB + Math.max(h0, h1, 0.001)));
      rockCol.push(c.r, c.g, c.b);
    }
    if (h0 < 0 || h1 < 0) {
      const b0 = Math.min(h0, 0), b1 = Math.min(h1, 0);
      water.push(x0, 0, z0, x0, b0, z0, x1, 0, z1, x1, 0, z1, x0, b0, z0, x1, b1, z1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(rock, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(rockCol, 3));
  const w = new THREE.BufferGeometry();
  w.setAttribute('position', new THREE.Float32BufferAttribute(water, 3));
  return [g, w];
}
const rockMat = (clip) => new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, clippingPlanes: clip ? [cut] : [] });
const waterMat = (clip) => new THREE.MeshBasicMaterial({ color: 0x2d6a96, transparent: true, opacity: 0.5, side: THREE.DoubleSide,
  depthWrite: false, clippingPlanes: clip ? [cut] : [] });
const line = (a, b, steps = 160) => [...Array(steps + 1).keys()].map((i) => [a[0] + ((b[0] - a[0]) * i) / steps, a[1] + ((b[1] - a[1]) * i) / steps]);
for (const edge of [line([G.xmin, G.zmax], [G.xmax, G.zmax]), line([G.xmin, G.zmin], [G.xmax, G.zmin]),
  line([G.xmin, G.zmin], [G.xmin, G.zmax]), line([G.xmax, G.zmin], [G.xmax, G.zmax])]) {
  const [g, w] = wall(edge);
  scene.add(new THREE.Mesh(g, rockMat(true)), new THREE.Mesh(w, waterMat(true)));
}
const cutRock = new THREE.Mesh(new THREE.BufferGeometry(), rockMat(false));
const cutWater = new THREE.Mesh(new THREE.BufferGeometry(), waterMat(false));
scene.add(cutRock, cutWater);
let cutAt = null;
function setCut(z) {
  cut.constant = z;
  const show = z < G.zmax - 0.01;
  cutRock.visible = cutWater.visible = show;
  if (!show || cutAt === z) return;
  cutAt = z;
  const [g, w] = wall(line([G.xmin, z], [G.xmax, z], 260));
  cutRock.geometry.dispose(); cutWater.geometry.dispose();
  cutRock.geometry = g; cutWater.geometry = w;
}

// Epicentre, hypocentre, seismic waves.
const E = S.epicentre, surf = heightAt(0, 0) * EX, hypoY = -E.depth_km * EX;
const red = new THREE.Color(0xff3b30);
const flat = (inner, outer, color) => {
  const m = new THREE.Mesh(new THREE.RingGeometry(inner, outer, 96), new THREE.MeshBasicMaterial({ color, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; return m;
};
const epiRing = flat(R * 0.035, R * 0.05, red);
epiRing.position.set(0, Math.max(surf, 0) + R * 0.004, 0);
scene.add(epiRing);
const pulses = [0, 1, 2].map(() => { const m = flat(0.92, 1, red); m.position.copy(epiRing.position); scene.add(m); return m; });
const hypo = new THREE.Mesh(new THREE.SphereGeometry(R * 0.018, 32, 16), new THREE.MeshBasicMaterial({ color: 0xff453a }));
hypo.position.set(0, hypoY, R * 0.004);
const glow = new THREE.Mesh(new THREE.CircleGeometry(R * 0.05, 48), new THREE.MeshBasicMaterial({ color: 0xff6b3d, transparent: true, opacity: 0.35, depthWrite: false }));
glow.position.set(0, hypoY, R * 0.006);
scene.add(hypo, glow);
const dashes = new THREE.Group();
const dashLen = (surf - hypoY) / 23;
for (let i = 0; i < 12; i++) {
  const d = new THREE.Mesh(new THREE.BoxGeometry(R * 0.004, dashLen, R * 0.004), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  d.position.set(0, surf - dashLen * (2 * i + 0.5), R * 0.005); dashes.add(d);
}
scene.add(dashes);
const waves = [0, 1, 2].map(() => {
  const m = new THREE.Mesh(new THREE.RingGeometry(0.94, 1, 96), new THREE.MeshBasicMaterial({ color: 0xffb000, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
  m.position.set(0, hypoY, R * 0.008); scene.add(m); return m;
});

// Fault: a dipping line through the hypocentre and two arrows sliding past each other.
const fault = new THREE.Group();
if (S.faulting === 'reverse' || S.faulting === 'normal') {
  const dip = THREE.MathUtils.degToRad(Math.min(70, Math.max(25, S.dip || 45)));
  const bar = new THREE.Mesh(new THREE.BoxGeometry(R * 0.5, R * 0.006, R * 0.002), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9 }));
  bar.rotation.z = -dip; fault.add(bar);
  const shape = new THREE.Shape();
  shape.moveTo(0, R * 0.03); shape.lineTo(R * 0.09, R * 0.03); shape.lineTo(R * 0.09, R * 0.06); shape.lineTo(R * 0.15, 0);
  shape.lineTo(R * 0.09, -R * 0.06); shape.lineTo(R * 0.09, -R * 0.03); shape.lineTo(0, -R * 0.03); shape.closePath();
  const arrowGeo = new THREE.ShapeGeometry(shape);
  const up = new THREE.Mesh(arrowGeo, new THREE.MeshBasicMaterial({ color: 0xffb000, transparent: true }));
  const down = new THREE.Mesh(arrowGeo, new THREE.MeshBasicMaterial({ color: 0x7fd3ff, transparent: true }));
  fault.add(up, down);
  fault.userData = { dip, up, down, sense: S.faulting === 'reverse' ? 1 : -1 };
  fault.position.set(0, hypoY, R * 0.01);
}
scene.add(fault);

// Places: cities, an earlier quake, aftershocks.
const labels = document.getElementById('labels');
const marks = [];
function addLabel(text, sub, x, z, cls, lift, rank) {
  const e = el('div', 'label ' + cls, text);
  if (sub) e.appendChild(el('span', 'sub', sub));
  labels.appendChild(e);
  marks.push({ el: e, p: new THREE.Vector3(x, Math.max(heightAt(x, z) * EX, 0) + R * lift, z), cls, rank });
  marks.sort((a, b) => a.rank - b.rank);
}
for (const [i, c] of S.cities.entries()) {
  const dot = new THREE.Mesh(new THREE.SphereGeometry(R * 0.009, 16, 8), new THREE.MeshBasicMaterial({ color: 0xffffff, clippingPlanes: [cut] }));
  dot.position.set(c.x, Math.max(heightAt(c.x, c.z) * EX, 0) + R * 0.004, c.z); scene.add(dot);
  addLabel(c.name, '', c.x, c.z, 'city', 0.035, c.name === S.ref ? 1 : 10 + i);
}
addLabel('Epicentre', `M${E.mag.toFixed(1)}`, 0, 0, 'epi', 0.07, 0);
const reach = new THREE.Group();
if (S.ref_xz) {
  const [rx, rz] = S.ref_xz, n = 28;
  const mat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false });
  const len = Math.hypot(rx, rz) / (2 * n);
  for (let i = 0; i < n; i++) {
    const u = (2 * i + 0.5) / (2 * n), x = rx * (1 - u), z = rz * (1 - u);
    const d = new THREE.Mesh(new THREE.BoxGeometry(R * 0.006, R * 0.003, len), mat);
    d.position.set(x, Math.max(heightAt(x, z) * EX, 0) + R * 0.006, z);
    d.rotation.y = Math.atan2(rx, rz);
    reach.add(d);
  }
  reach.userData.mat = mat;
}
scene.add(reach);
let histRing = null;
if (S.history) {
  histRing = flat(R * 0.04, R * 0.052, 0xc9d3df);
  histRing.material.opacity = 0;
  histRing.position.set(S.history.x, Math.max(heightAt(S.history.x, S.history.z) * EX, 0) + R * 0.004, S.history.z);
  scene.add(histRing);
  addLabel(`M${S.history.mag} · ${S.history.year}`, '', S.history.x, S.history.z, 'hist', 0.06, 2);
}
const shocks = S.aftershocks.map((a) => {
  const m = new THREE.Mesh(new THREE.SphereGeometry(R * (0.006 + 0.002 * a.mag), 12, 8), new THREE.MeshBasicMaterial({ color: 0xffd60a, transparent: true, opacity: 0 }));
  m.position.set(a.x, Math.max(heightAt(a.x, a.z) * EX, 0) + R * 0.005, a.z); scene.add(m); return m;
});

// Overlay text.
const card = document.getElementById('card'), big = document.getElementById('big'), small = document.getElementById('small');
const legend = document.getElementById('legend'), caps = document.getElementById('captions');
document.getElementById('credits').textContent = S.credits;
for (const l of S.legend) { const chip = el('span', '', l.roman); chip.style.background = l.color; legend.appendChild(chip); }
const TONES = { green: '#3ddc84', yellow: '#ffd60a', orange: '#ff9f0a', red: '#ff453a' };
const chunks = [];
{
  let cur = [];
  S.words.forEach((w, i) => {
    cur.push(i);
    const end = /[.,:;!?]$/.test(w.text) || cur.length >= 3 || i === S.words.length - 1 || S.words[i + 1].beat !== w.beat;
    if (end) { chunks.push(cur); cur = []; }
  });
}
let shownChunk = -1, shownWord = -2;
function captions(t) {
  const wi = S.words.findIndex((w) => t >= w.start && t < w.end + 0.12);
  let ci = wi >= 0 ? chunks.findIndex((c) => c.includes(wi)) : -1;
  if (ci < 0) {
    ci = chunks.findIndex((c) => S.words[c[c.length - 1]].end + 0.35 >= t && S.words[c[0]].start - 0.05 <= t);
  }
  if (ci === shownChunk && wi === shownWord) return;
  shownChunk = ci; shownWord = wi;
  caps.replaceChildren();
  if (ci < 0) return;
  chunks[ci].forEach((i, k) => {
    if (k) caps.appendChild(document.createTextNode(' '));
    caps.appendChild(el('span', i === wi ? 'now' : '', S.words[i].text));
  });
}

const v = new THREE.Vector3();
function place(t) {
  let k = 0;
  while (k < S.camera.length - 2 && S.camera[k + 1].t <= t) k++;
  const a = S.camera[k], b = S.camera[k + 1];
  const u = smooth(a.t, b.t, t);
  camera.position.set(...a.pos.map((p, i) => p + (b.pos[i] - p) * u));
  camera.lookAt(...a.look.map((p, i) => p + (b.look[i] - p) * u));
}

window.renderAt = (t) => {
  place(t);
  const cutShot = shot('cut'), after = S.shots.find((s) => cutShot && s.t0 > cutShot.t0 && s.name !== 'fault');
  let open = 0;
  if (cutShot) open = smooth(cutShot.t0, cutShot.t0 + 1.6, t) * (after ? 1 - smooth(after.t0, after.t0 + 1.4, t) : 1);
  setCut(open > 0.001 ? G.zmax * (1 - open) : G.zmax + 1);
  const deep = open > 0.97;
  hypo.visible = glow.visible = dashes.visible = deep;
  glow.scale.setScalar(1 + 0.25 * Math.sin(t * 5));
  waves.forEach((m, i) => {
    const ph = (t * 0.55 + i / 3) % 1;
    m.visible = deep; m.scale.setScalar(R * (0.03 + ph * 0.27)); m.material.opacity = 0.85 * (1 - ph);
  });
  pulses.forEach((m, i) => {
    const ph = (t * 0.4 + i / 3) % 1;
    m.scale.setScalar(R * (0.05 + ph * 0.3)); m.material.opacity = 0.7 * (1 - ph);
  });
  const fs = shot('fault');
  fault.visible = !!(fs && deep && t >= fs.t0 - 0.2);
  if (fault.visible && fault.userData.up) {
    const { dip, up, down, sense } = fault.userData;
    // The bar dips down to the right, so the hanging wall is the block above it. Reverse: hanging wall slides
    // up-dip; normal: down-dip. Arrows run parallel to the fault, one on each side.
    const s = ((t - fs.t0) * 0.35) % 1, along = R * (-0.05 + 0.1 * s);
    const a = new THREE.Vector2(-Math.cos(dip), Math.sin(dip)).multiplyScalar(sense);
    const n = new THREE.Vector2(Math.sin(dip), Math.cos(dip)).multiplyScalar(R * 0.075);
    const half = R * 0.075;
    up.position.set(n.x + a.x * (along - half), n.y + a.y * (along - half), 0);
    up.rotation.z = Math.atan2(a.y, a.x);
    down.position.set(-n.x - a.x * (along - half), -n.y - a.y * (along - half), 0);
    down.rotation.z = Math.atan2(-a.y, -a.x);
    up.material.opacity = down.material.opacity = Math.min(1, 1.5 - Math.abs(s - 0.5) * 2);
  }
  const sh = shot('shaking');
  mmiMat.opacity = sh ? smooth(sh.t0, sh.t0 + 1.2, t) * 0.95 : 0;
  legend.style.display = sh && t >= sh.t0 && t < sh.t1 ? 'flex' : 'none';
  const hs = shot('history');
  if (histRing) histRing.material.opacity = hs ? smooth(hs.t0, hs.t0 + 0.8, t) : 0;
  shocks.forEach((m, i) => { m.material.opacity = sh ? smooth(sh.t0 + 0.3 * i, sh.t0 + 0.3 * i + 0.5, t) : 0; });

  const s = S.shots.find((x) => t >= x.t0 && t < x.t1) || S.shots[S.shots.length - 1];
  const fade = Math.min(smooth(s.t0, s.t0 + 0.35, t), 1 - smooth(s.t1 - 0.3, s.t1, t));
  if (s.card) {
    if (big.textContent !== s.card.big) big.textContent = s.card.big;
    if (small.textContent !== s.card.small) small.textContent = s.card.small;
    big.style.color = TONES[s.card.tone] || '#ffffff';
  }
  card.style.opacity = s.card ? fade : 0;
  card.style.transform = `translateY(${(1 - fade) * 24}px)`;
  captions(t);

  const ap = shot('approach');
  if (reach.userData.mat) reach.userData.mat.opacity = ap ? 0.9 * smooth(ap.t0 + 0.4, ap.t0 + 1.2, t) * (1 - smooth(ap.t1, ap.t1 + 0.6, t)) : 0;
  const placed = [];
  for (const m of marks) {
    let on = m.cls === 'hist' ? !!(hs && t >= hs.t0) : (!ap || t >= ap.t0 - 0.3);
    if (m.p.z > cut.constant + 0.01) on = false;
    v.copy(m.p).project(camera);
    if (v.z > 1 || Math.abs(v.x) > 0.95 || Math.abs(v.y) > 0.95) on = false;
    if (on) {
      m.el.style.display = 'block';
      m.el.style.left = `${(v.x * 0.5 + 0.5) * W}px`; m.el.style.top = `${(-v.y * 0.5 + 0.5) * H}px`;
      const r = m.el.getBoundingClientRect();
      if (placed.some((q) => r.left < q.right + 10 && r.right > q.left - 10 && r.top < q.bottom + 6 && r.bottom > q.top - 6)) on = false;
      else placed.push(r);
    }
    m.el.style.display = on ? 'block' : 'none';
  }
  renderer.render(scene, camera);
  return true;
};
await document.fonts.ready;
window.renderAt(0);
window.ready = true;
