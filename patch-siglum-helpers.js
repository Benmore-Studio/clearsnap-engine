// Clearsnap: bump to retire every cached format and .aux cache built by an earlier engine.
const CLEARSNAP_CACHE_REV = '_c4';

// Clearsnap: what building the LuaLaTeX format reads (a native build's recorded files: babel's hyphen.cfg, the LaTeX
// picture fonts, Unicode data, the Lua libraries, luaotfload), beyond the bundles every LuaLaTeX compile loads. The
// bundled LuaTeX packages are older than TeX Live 2025 (luaotfload 3.23 against 3.28), and the bundled LuaLaTeX format
// doesn't load in wasm32, so LuaLaTeX skips both and takes LuaTeX packages from the mirror.
const LUALATEX_BUNDLES = ['babel', 'fonts-misc', 'tex-generic', 'tex-latex-misc'];
const LUALATEX_PACKAGES = ['luaotfload', 'lualibs', 'lua-uni-algos', 'l3backend'];
const LUALATEX_SKIP = ['fmt-lualatex', 'tex-luatex'];

// Clearsnap: a fingerprint of the project files a preamble reads (the project's own classes and packages, and files it
// \inputs, directly or from those files), added to the format's key so a format goes stale when one of them changes.
const PREAMBLE_STYLE_FILE = /\.(sty|cls|cfg|def|clo|fd|ldf)$/;
function preambleFilesKey(preamble, files) {
    const entries = Object.entries(files || {});
    if (!entries.length) return '';
    const text = data => (typeof data === 'string' ? data : new TextDecoder().decode(data));
    const named = t => [...t.matchAll(/\\(?:input|include|InputIfFileExists|subfile)\s*\{([^}]+)\}/g)].map(m => m[1].trim().replace(/\.tex$/, ''));
    const used = new Map(entries.filter(([p]) => PREAMBLE_STYLE_FILE.test(p)));
    let names = named(preamble);
    for (const [, data] of used) names.push(...named(text(data)));
    while (names.length) {
        const n = names.pop();
        for (const [p, data] of entries) {
            if (used.has(p) || p.replace(/\.tex$/, '') !== n) continue;
            used.set(p, data);
            names.push(...named(text(data)));
        }
    }
    if (!used.size) return '';
    return '-' + hashPreamble([...used].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([p, d]) => p + '\n' + text(d)).join('\n'));
}

// Clearsnap: whether a failed compile's first error is in the preamble or at \begin{document} (TeX's "l.N" context).
function clearsnapPreambleFailure(log, source) {
    const lines = String(log || '').split('\n');
    const i = lines.findIndex(l => l.startsWith('! '));
    const begin = source.indexOf('\\begin{document}');
    if (i < 0 || begin < 0) return false;
    const beginLine = source.slice(0, begin).split('\n').length;
    for (let j = i + 1; j < Math.min(i + 40, lines.length); j++) {
        const m = /^l\.(\d+)/.exec(lines[j]);
        if (m) return Number(m[1]) <= beginLine;
    }
    return false;
}

// Clearsnap: the figure cache's files (see the worker), kept across visits in the browser's storage. Each preamble
// keeps the list of pictures its document used, so a compile loads only those.
let memoCacheMounted = null;
function ensureMemoMount() {
    if (!memoCacheMounted) memoCacheMounted = fileSystem.mountAuto('/memo-cache').then(() => true, () => false);
    return memoCacheMounted;
}

