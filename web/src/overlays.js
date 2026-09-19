import * as Cesium from 'cesium';

export const DATA = import.meta.env.BASE_URL + 'data/';

function colorP(p) {
  // 0 -> gulhvit gjennomsiktig, 100 -> dyp rød
  const t = Math.max(0, Math.min(1, p / 100));
  const c = Cesium.Color.fromHsl(0.13 - 0.13 * t, 1.0, 0.72 - 0.35 * t, 0.35 + 0.65 * t);
  return c;
}

export class Overlays {
  constructor(viewer) {
    this.viewer = viewer;
    this.sources = {};      // id -> DataSource
    this.imagery = {};      // id -> ImageryLayer
    this.state = { segments: true, candidates: true, ngu: true, national: true, s2: false, metaller: false };
    this.candidates = [];   // {entity, props, lat, lon}
    this.nguPoints = [];
  }

  async loadIndex() {
    const r = await fetch(DATA + 'index.json');
    this.index = await r.json();
    return this.index;
  }

  async loadNational() {
    try {
      const gj = await Cesium.GeoJsonDataSource.load(DATA + 'national/ngu_gull.geojson', { clampToGround: true });
      gj.name = 'ngu';
      for (const e of gj.entities.values) {
        e.billboard = undefined;
        e.point = new Cesium.PointGraphics({ pixelSize: 7, color: Cesium.Color.fromCssColorString('#5dff8a'), outlineColor: Cesium.Color.BLACK, outlineWidth: 1.5,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND, disableDepthTestDistance: Number.POSITIVE_INFINITY, scaleByDistance: new Cesium.NearFarScalar(2e5, 1.0, 3e6, 0.45) });
        e.kind = 'ngu';
        const p = e.properties;
        this.nguPoints.push({ entity: e, name: p.name?.getValue() ?? 'NGU gull', objtype: p.objtype?.getValue?.() });
      }
      this.viewer.dataSources.add(gj); this.sources.ngu = gj;
    } catch (e) { console.warn('ngu_gull.geojson mangler', e); }
    try {
      const meta = await (await fetch(DATA + 'national/national.json')).json();
      const b = meta.bounds;
      const prov = await Cesium.SingleTileImageryProvider.fromUrl(DATA + 'national/score_1km.png', { rectangle: Cesium.Rectangle.fromDegrees(b.west, b.south, b.east, b.north), credit: '' });
      const layer = this.viewer.imageryLayers.addImageryProvider(prov);
      layer.alpha = 0.75; this.imagery.national = layer; this.national = meta;
    } catch (e) { console.warn('nasjonalt lag mangler', e); }
    this.viewer.scene.requestRender();
  }

  async loadArea(slug) {
    await this.unloadArea();
    const base = DATA + `areas/${slug}/`;
    this.area = await (await fetch(base + 'area.json')).json();
    this.area.base = base;
    const seg = await Cesium.GeoJsonDataSource.load(base + 'segments.geojson', { clampToGround: true });
    for (const e of seg.entities.values) {
      const P = e.properties.P.getValue();
      e.polyline.material = colorP(P);
      e.polyline.width = 2 + 6 * (P / 100);
      e.polyline.clampToGround = true;
      e.kind = 'segment';
    }
    seg.show = this.state.segments;
    this.viewer.dataSources.add(seg); this.sources.segments = seg;

    const cd = await Cesium.GeoJsonDataSource.load(base + 'candidates.geojson');
    this.candidates = [];
    for (const e of cd.entities.values) {
      const p = e.properties; const k = p.klasse.getValue(); const rank = p.rank.getValue();
      e.billboard = undefined;
      e.point = new Cesium.PointGraphics({ pixelSize: k === 'A' ? 11 : 9, color: Cesium.Color.fromCssColorString(k === 'A' ? '#ff4d4d' : k === 'B' ? '#ff9f43' : '#ffd23f'),
        outlineColor: Cesium.Color.BLACK, outlineWidth: 2, heightReference: Cesium.HeightReference.CLAMP_TO_GROUND, disableDepthTestDistance: Number.POSITIVE_INFINITY });
      e.label = new Cesium.LabelGraphics({ text: String(rank), font: 'bold 11px monospace', fillColor: Cesium.Color.BLACK, pixelOffset: new Cesium.Cartesian2(0, 0),
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND, disableDepthTestDistance: Number.POSITIVE_INFINITY, horizontalOrigin: Cesium.HorizontalOrigin.CENTER, verticalOrigin: Cesium.VerticalOrigin.CENTER });
      e.kind = 'candidate';
      const c = Cesium.Cartographic.fromCartesian(e.position.getValue(Cesium.JulianDate.now()));
      this.candidates.push({ entity: e, rank, klasse: k, lat: Cesium.Math.toDegrees(c.latitude), lon: Cesium.Math.toDegrees(c.longitude), props: this.plain(p) });
    }
    cd.show = this.state.candidates;
    this.viewer.dataSources.add(cd); this.sources.candidates = cd;
    this.candidates.sort((a, b) => a.rank - b.rank);

    try {
      const s2 = await (await fetch(base + 's2_anomaly.json')).json();
      const b = s2.bounds;
      const prov = await Cesium.SingleTileImageryProvider.fromUrl(base + 's2_anomaly.png', { rectangle: Cesium.Rectangle.fromDegrees(b.west, b.south, b.east, b.north), credit: '' });
      const layer = this.viewer.imageryLayers.addImageryProvider(prov);
      layer.show = this.state.s2; layer.alpha = 0.85; this.imagery.s2 = layer; this.area.s2 = s2;
    } catch (e) { /* ingen S2 */ }
    this.viewer.scene.requestRender();
    return this.area;
  }

  async unloadArea() {
    for (const k of ['segments', 'candidates']) if (this.sources[k]) { this.viewer.dataSources.remove(this.sources[k], true); delete this.sources[k]; }
    if (this.imagery.s2) { this.viewer.imageryLayers.remove(this.imagery.s2, true); delete this.imagery.s2; }
    this.candidates = []; this.area = null;
  }

  plain(props) {
    const o = {};
    for (const k of props.propertyNames) o[k] = props[k].getValue();
    return o;
  }

  async loadMetaller() {
    if (this.sources.metaller || this._metLoading) return;
    this._metLoading = true;
    try {
      const gj = await Cesium.GeoJsonDataSource.load(DATA + 'national/metaller_flater.geojson', { clampToGround: false, stroke: Cesium.Color.fromCssColorString('#5dff8a').withAlpha(0.8), fill: Cesium.Color.fromCssColorString('#5dff8a').withAlpha(0.15), strokeWidth: 1.5 });
      gj.show = this.state.metaller; this.viewer.dataSources.add(gj); this.sources.metaller = gj;
    } catch (e) { console.warn('metaller_flater mangler', e); }
    this.viewer.scene.requestRender();
  }

  /** Nasjonalt varmekart vises bare fra høyden (over 150 km); nær bakken forstyrrer det elvemodellen. */
  updateByAltitude(heightM) {
    if (this.imagery.national) this.imagery.national.show = this.state.national && heightM > 150000;
  }

  toggle(id, on) {
    this.state[id] = on;
    if (id === 'metaller' && on) this.loadMetaller();
    if (id === 'national') { this.updateByAltitude(this.viewer.camera.positionCartographic.height); return this.viewer.scene.requestRender(); }
    if (this.sources[id]) this.sources[id].show = on;
    if (this.imagery[id]) this.imagery[id].show = on;
    this.viewer.scene.requestRender();
  }
}
