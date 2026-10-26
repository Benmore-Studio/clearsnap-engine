// runner.js - the in-browser compiler. The Clearsnap editor embeds this page (engine.clearsnap.dev) in a hidden
// iframe and posts it documents; TeX Live 2025 compiled to WebAssembly (Siglum / BusyTeX, MIT) typesets them in a
// worker and the PDF, log and SyncTeX go back to the editor. Nothing is uploaded: documents stay on the device.
// Running on its own origin keeps the engine away from the editor's cookies and pages.

// Siglum's sources, patched by patch-siglum.py so packages load from our TeX Live 2025 mirror.
import { SiglumCompiler } from '../build/siglum/index.js';
import { saveManifestVersion } from '../build/siglum/storage.js';
// The font files the editor's templates use (make-bundles-v5.py).
import PREFETCH from './prefetch.json';

// The bundle set this page uses (make-bundles.py). The engine keeps its own copy of the manifests in browser storage;
// when the set changes, that copy is dropped once so the new bundles (biblatex) are seen. v5: the font bundles are
// fetched a file at a time.
const BUNDLES_REV = 'v5';

const EDITORS = new Set([
  'https://www.clearsnap.dev',
  'https://clearsnap.dev',
  'https://proof-bt6ad8-dev.benmore.ai',
  'https://proof-bt6ad8.benmore.ai',
]);

let editor = null; // the origin that is driving us
let ready = null;
const post = (msg, transfer = []) => { if (editor) parent.postMessage(msg, editor, transfer); };

const compiler = new SiglumCompiler({
  bundlesUrl: '/v5/bundles',
  // Brotli-compressed (8 MB instead of 31 MB); see deploy-texlive.sh.
  wasmUrl: '/v4/busytex.wasm',
  jsUrl: '/v4/busytex.js',
  workerUrl: '/worker.js',
  // Any TeX Live 2025 package the bundles don't have is fetched when a document first needs it, from the static
  // mirror at /tl2025 on this same host (make-texlive.py), and cached in the browser.
  enableCtan: true,
  ctanProxyUrl: location.origin + '/tl2025',
  // BibTeX styles (plain, unsrt, alpha, natbib's plainnat...: 40 KB) and the graphics/colour drivers (xcolor
  // needs color.cfg even when a class loads it), loaded with every compile.
  eagerBundles: ['bibtex', 'graphics'],
  // Fetch-and-retry rounds per compile: a class like acmart pulls in dozens of packages on its first compile.
  maxRetries: 40,
  // Its PDF cache is keyed by the main file alone, so edits to other files (a .bib, an \\input, a figure) came
  // back as the old PDF. The editor only compiles after a change anyway.
  enableDocCache: false,
  verbose: false,
  onProgress: (stage, detail) => post({ type: 'progress', stage, detail: String(detail ?? '') }),
});

async function freshManifests() {
  try {
    if (localStorage.getItem('clearsnap-bundles') === BUNDLES_REV) return;
    await saveManifestVersion(0);
    localStorage.setItem('clearsnap-bundles', BUNDLES_REV);
  } catch (e) {}
}
// The templates' font files load alongside the engine; the worker then reads them from the browser's cache.
const prefetch = () => { for (const p of PREFETCH) fetch('/v5/files' + p).then(r => r.arrayBuffer()).catch(() => {}); };
const init = () => (ready ||= (prefetch(), freshManifests().then(() => compiler.init())).catch(err => { ready = null; throw err; }));

addEventListener('message', async e => {
  if (e.source !== parent || !EDITORS.has(e.origin)) return;
  editor = e.origin;
  const m = e.data || {};
  if (m.type === 'init') {
    try { await init(); post({ type: 'ready' }); }
    catch (err) { post({ type: 'failed', error: String(err?.message || err) }); }
    return;
  }
  if (m.type === 'compile') {
    const t0 = performance.now();
    try {
      await init();
      const res = await compiler.compile(m.source, { engine: m.engine, additionalFiles: m.files || {} });
      const pdf = res.pdf ? res.pdf.slice() : null; // a private copy we can transfer
      post({
        type: 'result', id: m.id, ok: !!res.success, pdf, log: res.log || '', synctex: res.syncTexData || null,
        error: res.error || null, ms: Math.round(performance.now() - t0),
      }, pdf ? [pdf.buffer] : []);
    } catch (err) {
      post({ type: 'result', id: m.id, ok: false, pdf: null, log: '', synctex: null, error: String(err?.message || err), ms: Math.round(performance.now() - t0) });
    }
  }
});

// Tell the embedding page we're listening. No data in it, so any origin may hear it.
parent.postMessage({ type: 'loaded' }, '*');
