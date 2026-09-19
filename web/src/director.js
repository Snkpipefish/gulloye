import * as Cesium from 'cesium';

const NORWAY = { lon: 14.5, lat: 65.0, h: 3.4e6 };

export class Director {
  constructor(viewer) { this.viewer = viewer; this.skip = false; }

  setSpace() {
    this.viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(10, 40, 2.6e7), orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 } });
  }

  flyNorway(duration = 4) {
    return new Promise((res) => this.viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(NORWAY.lon, NORWAY.lat, NORWAY.h),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-88), roll: 0 }, duration, complete: res, cancel: res }));
  }

  flyArea(bbox, duration = 3.5) {
    const [s, w, n, e] = bbox;
    const cLat = (s + n) / 2, cLon = (w + e) / 2;
    const hm = (n - s) * 111000, wm = (e - w) * 111000 * Math.cos(Cesium.Math.toRadians(cLat));
    const height = Math.max(hm, wm) * 1.05;
    // Skrått innsyn fra sør: kamera litt sør for senter, pitch −60°
    const dest = Cesium.Cartesian3.fromDegrees(cLon, cLat - (n - s) * 0.45, height);
    return new Promise((res) => this.viewer.camera.flyTo({ destination: dest, duration, complete: res, cancel: res,
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-62), roll: 0 } }));
  }

  flyPoint(lat, lon, height = 1800, duration = 2.5) {
    return new Promise((res) => this.viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat - 0.012, height),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-50), roll: 0 }, duration, complete: res, cancel: res }));
  }

  async type(el, lines, speed = 22) {
    for (const line of lines) {
      if (this.skip) return;
      el.textContent = '';
      for (const ch of line) { if (this.skip) return; el.textContent += ch; await new Promise((r) => setTimeout(r, speed)); }
      await new Promise((r) => setTimeout(r, 420));
    }
  }
}
