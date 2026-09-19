import * as Cesium from 'cesium';

const COMMON = `
uniform sampler2D colorTexture;
in vec2 v_textureCoordinates;
uniform float u_time;
float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
float rnd(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233)) + u_time) * 43758.5453); }
`;

export const SENSORS = {
  crt: { label: 'CRT', hud: 'SENSOR: EO/CRT', glsl: COMMON + `
void main() {
  vec2 uv = v_textureCoordinates;
  vec2 d = uv - 0.5; float r2 = dot(d, d);
  uv = 0.5 + d * (1.0 + 0.08 * r2);              // lett tønnefortegning
  float off = 0.0016 * (0.5 + r2);
  float rC = texture(colorTexture, uv + vec2(off, 0.0)).r;
  float gC = texture(colorTexture, uv).g;
  float bC = texture(colorTexture, uv - vec2(off, 0.0)).b;
  vec3 c = vec3(rC, gC, bC);
  float scan = 0.85 + 0.15 * sin(uv.y * 900.0);
  c *= scan;
  c = mix(c, vec3(luma(c)) * vec3(0.9, 1.05, 0.95), 0.35);
  c *= 1.0 - 0.9 * r2 * r2;
  c += 0.03 * rnd(uv * 3.0);
  out_FragColor = vec4(c, 1.0);
}` },
  nvg: { label: 'NVG', hud: 'SENSOR: NVG GEN3', glsl: COMMON + `
void main() {
  vec2 uv = v_textureCoordinates;
  vec3 c = texture(colorTexture, uv).rgb;
  float l = luma(c);
  l = pow(l * 1.9, 0.75);
  float n = rnd(uv * 2.0) * 0.18;
  vec3 g = vec3(0.12, 1.0, 0.35) * (l + n) + vec3(0.0, 0.06, 0.0);
  vec2 d = (uv - 0.5) * vec2(1.6, 1.0); float r = length(d);
  g *= smoothstep(0.85, 0.55, r);
  g *= 0.9 + 0.1 * sin(uv.y * 700.0);
  out_FragColor = vec4(g, 1.0);
}` },
  flir: { label: 'FLIR', hud: 'SENSOR: IR/FLIR (IRONBOW)', glsl: COMMON + `
vec3 ironbow(float t) {
  vec3 a = vec3(0.0, 0.0, 0.0), b = vec3(0.35, 0.0, 0.55), c = vec3(0.95, 0.2, 0.05), d = vec3(1.0, 0.85, 0.1), e = vec3(1.0);
  if (t < 0.25) return mix(a, b, t / 0.25);
  if (t < 0.5)  return mix(b, c, (t - 0.25) / 0.25);
  if (t < 0.75) return mix(c, d, (t - 0.5) / 0.25);
  return mix(d, e, (t - 0.75) / 0.25);
}
void main() {
  vec2 uv = v_textureCoordinates;
  vec3 c = texture(colorTexture, uv).rgb;
  float l = luma(c);
  // vann/skygge = kaldt, lys mark = varmt; forsterk kontrast
  float t = smoothstep(0.05, 0.9, l);
  t += 0.02 * rnd(uv);
  out_FragColor = vec4(ironbow(clamp(t, 0.0, 1.0)), 1.0);
}` },
  noir: { label: 'NOIR', hud: 'SENSOR: PAN/NOIR', glsl: COMMON + `
void main() {
  vec2 uv = v_textureCoordinates;
  vec3 c = texture(colorTexture, uv).rgb;
  float l = luma(c);
  l = clamp((l - 0.45) * 1.9 + 0.45, 0.0, 1.0);
  l += 0.05 * rnd(uv * 4.0);
  vec2 d = uv - 0.5; float r2 = dot(d, d);
  l *= 1.0 - 1.1 * r2;
  out_FragColor = vec4(vec3(l), 1.0);
}` },
};

export class Sensors {
  constructor(viewer) {
    this.viewer = viewer; this.stage = null; this.current = null; this.t0 = performance.now();
    this.onChange = () => {};
  }
  set(id) {
    const scene = this.viewer.scene;
    if (this.stage) { scene.postProcessStages.remove(this.stage); this.stage = null; }
    document.getElementById('sensor-overlay').className = id ? `sensor-${id}` : 'sensor-none';
    this.current = id || null;
    if (id && SENSORS[id]) {
      this.stage = new Cesium.PostProcessStage({ fragmentShader: SENSORS[id].glsl, uniforms: { u_time: () => (performance.now() - this.t0) / 1000 } });
      scene.postProcessStages.add(this.stage);
      scene.requestRenderMode = false;       // støy/scanlines skal animere
    } else {
      scene.requestRenderMode = true;
    }
    scene.requestRender();
    this.onChange(this.current);
  }
}
