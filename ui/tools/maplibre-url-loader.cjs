// From upstream OSIRIS (MIT). MapLibre 6 builds its worker URL at run time
// with `new URL(variable, import.meta.url)`; Turbopack mistakes that for a
// build-time asset import and fails ("Can't resolve <dynamic>"). Qualifying
// the same native constructor as globalThis.URL keeps run-time behaviour and
// stops Turbopack treating it as an import.
module.exports = function maplibreUrlLoader(source) {
  return source.replace(/new URL\(([$\w]+),\s*import\.meta\.url\)/g, 'new globalThis.URL($1,import.meta.url)');
};
