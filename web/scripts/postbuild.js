// vite-plugin-cesium kopierer Cesium-ressursene til dist/<base>/cesium når BASE_PATH er satt.
// GitHub Pages serverer dist/ under <base>, så mappen må flyttes til dist/cesium.
import { existsSync, renameSync, rmSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
const base = (process.env.BASE_PATH ?? '/').replace(/^\/|\/$/g, '');
if (base) {
  const wrong = join('dist', base, 'cesium');
  const right = join('dist', 'cesium');
  if (existsSync(wrong)) {
    if (existsSync(right)) rmSync(right, { recursive: true });
    renameSync(wrong, right);
    if (readdirSync(join('dist', base)).length === 0) rmSync(join('dist', base), { recursive: true });
    console.log(`postbuild: flyttet ${wrong} -> ${right}`);
  }
}
