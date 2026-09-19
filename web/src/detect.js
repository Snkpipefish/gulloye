import * as Cesium from 'cesium';

/** Skjermbokser rundt kandidater og NGU-punkter (postRender). */
export class DetectionBoxes {
  constructor(viewer) {
    this.viewer = viewer; this.el = document.getElementById('boxes'); this.items = []; this.pool = [];
    viewer.scene.postRender.addEventListener(() => this.update());
  }
  setItems(items) { this.items = items; this.viewer.scene.requestRender(); }
  update() {
    const scene = this.viewer.scene;
    const occ = new Cesium.EllipsoidalOccluder(Cesium.Ellipsoid.WGS84, scene.camera.positionWC);
    const toWin = Cesium.SceneTransforms.worldToWindowCoordinates || Cesium.SceneTransforms.wgs84ToWindowCoordinates;
    const camH = scene.camera.positionCartographic.height;
    let n = 0;
    for (const it of this.items) {
      if (it.minHeight && camH > it.minHeight) continue;
      const pos = it.entity.position.getValue(Cesium.JulianDate.now());
      if (!pos || !occ.isPointVisible(pos)) continue;
      const w = toWin(scene, pos);
      if (!w || w.x < -50 || w.y < -50 || w.x > scene.canvas.clientWidth + 50 || w.y > scene.canvas.clientHeight + 50) continue;
      let el = this.pool[n];
      if (!el) { el = document.createElement('div'); el.innerHTML = '<i></i><b></b>'; this.el.appendChild(el); this.pool[n] = el; }
      el.className = 'box ' + it.cls;
      el.style.left = w.x + 'px'; el.style.top = w.y + 'px';
      el.firstElementChild.nextElementSibling.textContent = it.label;
      el.style.display = 'block';
      n++;
    }
    for (let i = n; i < this.pool.length; i++) this.pool[i].style.display = 'none';
  }
}
