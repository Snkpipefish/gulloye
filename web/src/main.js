import * as Cesium from 'cesium';
import { createViewer } from './viewer.js';
import { BASEMAPS, BasemapStack } from './basemaps.js';
import { Overlays } from './overlays.js';
import { SENSORS, Sensors } from './sensors/index.js';
import { DetectionBoxes } from './detect.js';
import { Director } from './director.js';
import { TargetPanel } from './hud/target.js';

const $ = (id) => document.getElementById(id);
const status = (t) => { $('status').textContent = t; };

async function main() {
  status('STARTER GLOBUS…');
  const viewer = await createViewer();
  const basemaps = new BasemapStack(viewer);
  const overlays = new Overlays(viewer);
  const sensors = new Sensors(viewer);
  const boxes = new DetectionBoxes(viewer);
  const director = new Director(viewer);
  const target = new TargetPanel($('target'), overlays);
  let currentArea = null;
  let areas = [];
  window.__g = { viewer, basemaps, overlays, sensors, boxes, director, target, Cesium };

  // --- kartstabel-chips
  const chipBox = $('basemap-chips');
  for (const b of BASEMAPS) {
    const el = document.createElement('div'); el.className = 'chip'; el.textContent = b.label; el.dataset.id = b.id;
    el.onclick = () => basemaps.set(b.id); chipBox.appendChild(el);
  }
  basemaps.onChange = (id) => { for (const el of chipBox.children) el.classList.toggle('on', el.dataset.id === id); };
  basemaps.set('esri');

  // --- sensor-chips
  const sBox = $('sensor-chips');
  const addSensor = (id, label) => { const el = document.createElement('div'); el.className = 'chip'; el.textContent = label; el.dataset.id = id || ''; el.onclick = () => sensors.set(id); sBox.appendChild(el); };
  addSensor(null, 'EO'); for (const [id, s] of Object.entries(SENSORS)) addSensor(id, s.label);
  sensors.onChange = (id) => { for (const el of sBox.children) el.classList.toggle('on', (el.dataset.id || null) === id); $('sensor-label').textContent = id ? SENSORS[id].hud : 'SENSOR: EO/VIS'; };
  sensors.set(null);

  // --- lag-brytere
  const toggles = [['national', 'NASJONALT POTENSIAL (1 km)'], ['ngu', 'NGU GULLFOREKOMSTER'], ['metaller', 'NGU METALLFLATER'], ['segments', 'ELVEINDEKS P (100 m)'], ['candidates', 'KANDIDATPUNKTER A/B/C'], ['s2', 'SENTINEL-2 ANOMALI']];
  const tBox = $('layer-toggles');
  for (const [id, label] of toggles) {
    const l = document.createElement('label'); const i = document.createElement('input'); i.type = 'checkbox'; i.checked = overlays.state[id];
    i.onchange = () => { overlays.toggle(id, i.checked); refreshBoxes(); };
    l.append(i, document.createTextNode(label)); tBox.appendChild(l);
  }

  // --- klokke + koordinater
  setInterval(() => { $('clock').textContent = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC'; }, 1000);
  viewer.camera.changed.addEventListener(updateCoords);
  viewer.camera.percentageChanged = 0.01;
  function updateCoords() {
    const c = viewer.camera.positionCartographic;
    $('coords').textContent = `LAT ${Cesium.Math.toDegrees(c.latitude).toFixed(4)}  LON ${Cesium.Math.toDegrees(c.longitude).toFixed(4)}  ALT ${(c.height / 1000).toFixed(1)} km`;
  }

  // --- klikk
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((m) => {
    const picked = viewer.scene.pick(m.position);
    const ent = picked?.id;
    if (ent && ent.kind === 'candidate') {
      const c = overlays.candidates.find((x) => x.entity === ent); if (c) target.showCandidate(c);
    } else if (ent && ent.kind === 'segment') {
      target.showSegment(overlays.plain(ent.properties));
    } else if (ent && ent.kind === 'ngu') {
      target.showNgu(overlays.plain(ent.properties));
    } else if (!ent) {
      const ray = viewer.camera.getPickRay(m.position); const pos = viewer.scene.globe.pick(ray, viewer.scene);
      if (pos && overlays.state.national && overlays.national && !currentArea) {
        const cg = Cesium.Cartographic.fromCartesian(pos); target.showNational(overlays.national, Cesium.Math.toDegrees(cg.latitude), Cesium.Math.toDegrees(cg.longitude));
      }
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  function refreshBoxes() {
    const items = [];
    if (overlays.state.candidates) for (const c of overlays.candidates) items.push({ entity: c.entity, cls: c.klasse, label: `${c.rank}${c.klasse} P${Math.round(c.props.P)}`, minHeight: 120000 });
    if (overlays.state.ngu) for (const p of overlays.nguPoints) items.push({ entity: p.entity, cls: 'ngu', label: p.name.toUpperCase().slice(0, 22), minHeight: 250000 });
    boxes.setItems(items);
  }

  // --- områder
  async function gotoArea(slug, fly = true) {
    const a = areas.find((x) => x.slug === slug); if (!a) return;
    status(`LASTER MÅL: ${a.name.toUpperCase()}`);
    target.hide();
    currentArea = slug;
    for (const el of $('area-list').children) el.classList.toggle('on', el.dataset.slug === slug);
    $('area-name').textContent = a.name;
    if (fly) await director.flyArea(a.bbox);
    const meta = await overlays.loadArea(slug);
    refreshBoxes();
    status(`MÅL LÅST · ${meta.stats.segmenter} SEGMENTER · ${meta.stats.kandidater} KANDIDATER`);
    location.hash = slug;
  }
  async function gotoNorway() {
    currentArea = null; $('area-name').textContent = 'NORGE'; target.hide();
    await overlays.unloadArea(); refreshBoxes();
    for (const el of $('area-list').children) el.classList.remove('on');
    await director.flyNorway(3); status('OVERSIKT · NASJONALT POTENSIAL'); location.hash = '';
  }

  // --- taster
  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    const k = e.key;
    if (k === 'm' || k === 'M') basemaps.next();
    else if (k === 'Escape') { sensors.set(null); target.hide(); $('help').classList.add('hidden'); }
    else if (k === 'F1') { e.preventDefault(); sensors.set('crt'); }
    else if (k === 'F2') { e.preventDefault(); sensors.set('nvg'); }
    else if (k === 'F3') { e.preventDefault(); sensors.set('flir'); }
    else if (k === 'F4') { e.preventDefault(); sensors.set('noir'); }
    else if (k === 'h' || k === 'H') $('help').classList.toggle('hidden');
    else if (k === 'l' || k === 'L') $('layers-panel').classList.toggle('hidden');
    else if (k === '0') gotoNorway();
    else if (/^[1-9]$/.test(k)) { const a = areas[Number(k) - 1]; if (a) gotoArea(a.slug); }
    else if (/^[abcABC]$/.test(k)) {
      const kl = k.toUpperCase(); const c = overlays.candidates.find((x) => x.klasse === kl);
      if (c) { director.flyPoint(c.lat, c.lon).then(() => target.showCandidate(c)); }
    }
  });
  $('help-link').onclick = (e) => { e.preventDefault(); $('help').classList.toggle('hidden'); };
  $('help-close').onclick = () => $('help').classList.add('hidden');

  // --- data
  status('LASTER DATAINDEKS…');
  const idx = await overlays.loadIndex();
  areas = idx.areas;
  const list = $('area-list');
  areas.forEach((a, i) => {
    const row = document.createElement('div'); row.className = 'row'; row.dataset.slug = a.slug;
    row.innerHTML = `<span><span class="n">${i + 1}</span> ${a.name.toUpperCase()}</span><span class="n">${a.kandidater} PKT</span>`;
    row.onclick = () => gotoArea(a.slug); list.appendChild(row);
  });
  const row = document.createElement('div'); row.className = 'row'; row.innerHTML = '<span><span class="n">0</span> NORGE</span><span class="n">OVERSIKT</span>'; row.onclick = gotoNorway; list.appendChild(row);
  overlays.loadNational().then(refreshBoxes);

  // --- intro
  director.setSpace();
  const introEl = $('intro'); const skip = $('skip');
  skip.onclick = () => { director.skip = true; viewer.camera.cancelFlight(); };
  const hashArea = location.hash.replace('#', '');
  const first = areas.find((a) => a.slug === hashArea) || areas[0];
  const typing = director.type($('intro-text'), ['GULLØYE ONLINE', 'KOBLER TIL: NGU · KARTVERKET · COPERNICUS · OSM', 'SATELLITT I POSISJON', first ? `MÅL: ${first.name.toUpperCase()}` : 'OVERSIKT NORGE']);
  await director.flyNorway(5);
  await typing;
  introEl.classList.add('hidden');
  if (first) await gotoArea(first.slug, !director.skip); else gotoNorway();
  updateCoords();
}

main().catch((e) => { console.error(e); status('FEIL: ' + e.message); });
