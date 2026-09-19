import * as Cesium from 'cesium';

export const TERRAIN_URL = 'https://terrain.reearth.land/cesium-mesh/ellipsoid';

export async function createViewer() {
  const ionToken = import.meta.env.VITE_CESIUM_ION_TOKEN;
  if (ionToken) Cesium.Ion.defaultAccessToken = ionToken;

  const viewer = new Cesium.Viewer('cesium', {
    baseLayer: false,
    animation: false, timeline: false, geocoder: false, homeButton: false, sceneModePicker: false,
    baseLayerPicker: false, navigationHelpButton: false, infoBox: false, selectionIndicator: false,
    fullscreenButton: false, vrButton: false,
    requestRenderMode: true, maximumRenderTimeChange: Infinity,
    msaaSamples: 2,
  });
  const scene = viewer.scene;
  scene.backgroundColor = Cesium.Color.fromCssColorString('#050608');
  scene.globe.baseColor = Cesium.Color.fromCssColorString('#0b0f14');
  scene.globe.enableLighting = false;
  scene.globe.showGroundAtmosphere = true;
  scene.skyAtmosphere.brightnessShift = -0.35;
  scene.skyAtmosphere.saturationShift = -0.3;
  scene.fog.enabled = true;
  scene.fog.density = 0.00025;
  scene.screenSpaceCameraController.minimumZoomDistance = 80;
  viewer.cesiumWidget.creditContainer.style.display = 'none';

  // Terreng: nøkkelfritt Re:Earth-mesh (som gods-eye-view), fallback ellipsoide. Cesium ion om token finnes.
  try {
    if (ionToken) {
      scene.setTerrain(Cesium.Terrain.fromWorldTerrain({ requestVertexNormals: false }));
    } else {
      const tp = await Cesium.CesiumTerrainProvider.fromUrl(TERRAIN_URL, { requestVertexNormals: false });
      scene.terrainProvider = tp;
    }
    scene.globe.depthTestAgainstTerrain = false;
  } catch (e) {
    console.warn('Terreng utilgjengelig, bruker ellipsoide', e);
    scene.terrainProvider = new Cesium.EllipsoidTerrainProvider();
  }
  return viewer;
}

export function render(viewer) { viewer.scene.requestRender(); }
