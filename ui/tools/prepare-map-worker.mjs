// From upstream OSIRIS (MIT). MapLibre 6's worker is a module that imports a
// sibling shared module. Copy both from the installed package into
// public/vendor/maplibre/<version>/ so Horus serves its own worker (no CDN,
// works air-gapped). Runs before `npm run dev` and `npm run build`.
// The output is generated, not committed (.gitignore); older versions are pruned.
import { copyFile, mkdir, readdir, readFile, rm } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const source = new URL('node_modules/maplibre-gl/', root);
const { version } = JSON.parse(await readFile(new URL('package.json', source), 'utf8'));
const vendor = new URL('public/vendor/maplibre/', root);
await mkdir(new URL(`${version}/`, vendor), { recursive: true });
for (const file of ['dist/maplibre-gl-worker.mjs', 'dist/maplibre-gl-shared.mjs', 'LICENSE.txt']) {
  await copyFile(new URL(file, source), new URL(`${version}/${file.split('/').at(-1)}`, vendor));
}
for (const entry of await readdir(vendor, { withFileTypes: true })) {
  if (entry.isDirectory() && entry.name !== version) {
    await rm(new URL(`${entry.name}/`, vendor), { recursive: true, force: true });
    console.log(`prepare-map-worker: pruned maplibre ${entry.name}`);
  }
}
console.log(`prepare-map-worker: maplibre ${version} worker in public/vendor/maplibre/${version}/`);
