import * as Cesium from 'cesium';

const url = (t) => new Cesium.UrlTemplateImageryProvider({ url: t, maximumLevel: 18, credit: '' });

export const BASEMAPS = [
  { id: 'esri', label: 'ESRI SAT', make: () => url('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}') },
  { id: 'eox', label: 'S2 CLOUDLESS', make: () => url('https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg') },
  { id: 'topo', label: 'TOPO', make: () => url('https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png') },
  { id: 'graa', label: 'TOPO GRÅ', make: () => url('https://cache.kartverket.no/v1/wmts/1.0.0/topograatone/default/webmercator/{z}/{y}/{x}.png') },
  { id: 'amt', label: 'AMTSKART 1800', make: () => new Cesium.WebMapServiceImageryProvider({
      url: 'https://wms.geonorge.no/skwms1/wms.historiskekart', layers: 'amt1',
      parameters: { transparent: true, format: 'image/png', version: '1.3.0' },
      tilingScheme: new Cesium.WebMercatorTilingScheme(), tileWidth: 512, tileHeight: 512, credit: '' }) },
  { id: 'berg', label: 'NGU BERGGRUNN', make: () => new Cesium.WebMapServiceImageryProvider({
      url: 'https://geo.ngu.no/mapserver/BerggrunnWMS3', layers: 'Berggrunn_nasjonal_hovedbergarter,Berggrunn_regional_hovedbergarter',
      parameters: { transparent: true, format: 'image/png', version: '1.3.0' },
      tilingScheme: new Cesium.WebMercatorTilingScheme(), tileWidth: 512, tileHeight: 512, credit: '' }) },
];

export class BasemapStack {
  constructor(viewer) {
    this.viewer = viewer;
    this.layers = viewer.imageryLayers;
    this.current = null;
    this.base = null;
    this.onChange = () => {};
  }
  set(id) {
    const def = BASEMAPS.find((b) => b.id === id) || BASEMAPS[0];
    if (this.base) this.layers.remove(this.base, true);
    const provider = def.make();
    this.base = this.layers.addImageryProvider(provider, 0);
    if (def.id === 'berg' || def.id === 'amt') {
      // legg satellitt under for kontekst
      this.underlay = this.layers.addImageryProvider(BASEMAPS[0].make(), 0);
      this.base.alpha = def.id === 'berg' ? 0.75 : 0.92;
    } else if (this.underlay) { this.layers.remove(this.underlay, true); this.underlay = null; }
    this.current = def.id;
    this.viewer.scene.requestRender();
    this.onChange(def.id);
  }
  next() {
    const i = BASEMAPS.findIndex((b) => b.id === this.current);
    this.set(BASEMAPS[(i + 1) % BASEMAPS.length].id);
  }
}
