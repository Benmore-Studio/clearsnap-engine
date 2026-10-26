// ============ Clearsnap: LuaLaTeX ============
// LuaHBTeX is in the same binary. Its LaTeX format can't come prebuilt: one dumped by a native 64-bit LuaTeX doesn't
// load in wasm32 ("Fatal format file error"). So the worker builds it the first time a LuaLaTeX document compiles (a
// few seconds), keeps it for its life, and sends it back once so the compiler can keep it across visits.
let clearsnapLuaFmt = null;
let clearsnapLuaFmtNew = false;

// A new array for each run: Emscripten's callMain puts the program name in front of the array it is given.
const luaArgs = () => ['luahbtex', '-progname=lualatex', '--no-shell-escape', '--interaction=nonstopmode', '--halt-on-error',
    '--synctex=-1', '--fmt=/lualatex.fmt', '/document.tex'];

// LuaTeX dumps its format gzip-compressed and inflates it on every run (about a twentieth of a LuaLaTeX compile); it
// reads an uncompressed one just as well, so the worker keeps it inflated.
async function luaFormatInflated() {
    if (clearsnapLuaFmt && clearsnapLuaFmt[0] === 0x1f && clearsnapLuaFmt[1] === 0x8b && typeof DecompressionStream !== 'undefined') {
        try { clearsnapLuaFmt = new Uint8Array(await new Response(new Blob([clearsnapLuaFmt]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer()); } catch (e) {}
    }
}

// Puts the LuaLaTeX format and luaotfload's cache in place, building the format if needed. A failed build's log becomes the document's, so the
// missing-file retries fetch what it lacked.
function luaFormat(Module, FS) {
    if (clearsnapLuaFmt) {
        FS.writeFile('/lualatex.fmt', clearsnapLuaFmt);
        writeLuaCache(FS);
        return { exit_code: 0, stdout: '', stderr: '' };
    }
    workerLog('Building the LuaLaTeX format');
    workerProgress('compile', 'Preparing LuaLaTeX...');
    const t0 = performance.now();
    const r = Module.callMainWithRedirects(['luahbtex', '-ini', '-jobname=lualatex', '-progname=lualatex',
        '-interaction=nonstopmode', 'lualatex.ini']);
    let fmt = null;
    try { fmt = FS.readFile('/lualatex.fmt'); } catch (e) {}
    if (r.exit_code === 0 && fmt && fmt.length) {
        clearsnapLuaFmt = fmt;
        clearsnapLuaFmtNew = true;
        workerLog(`LuaLaTeX format built: ${(fmt.length / 1048576).toFixed(1)}MB in ${Math.round(performance.now() - t0)}ms`);
        return r;
    }
    try { FS.writeFile('/document.log', FS.readFile('/lualatex.log')); } catch (e) {}
    return r;
}

// luaotfload's font database and the fonts it has parsed (luatex-cache), kept between runs and sent back so the
// compiler keeps them across visits: each run starts on a fresh file system, and luaotfload would otherwise build its
// database and parse each OpenType font again every time.
const LUA_CACHE = '/texlive/texmf-dist/texmf-var/luatex-cache';
const clearsnapLuaCache = new Map(); // path under LUA_CACHE -> bytes
const clearsnapLuaCacheFresh = new Set();

function writeLuaCache(FS) {
    for (const [rel, data] of clearsnapLuaCache) {
        const path = LUA_CACHE + '/' + rel;
        let dir = '';
        for (const part of path.split('/').slice(1, -1)) { dir += '/' + part; try { FS.mkdir(dir); } catch (e) {} }
        try { FS.writeFile(path, data); } catch (e) {}
    }
}

function readLuaCache(FS, dir = LUA_CACHE) {
    let names = [];
    try { names = FS.readdir(dir); } catch (e) { return; }
    for (const n of names) {
        if (n === '.' || n === '..') continue;
        const path = dir + '/' + n;
        let st;
        try { st = FS.stat(path); } catch (e) { continue; }
        if (FS.isDir(st.mode)) { readLuaCache(FS, path); continue; }
        const rel = path.slice(LUA_CACHE.length + 1), old = clearsnapLuaCache.get(rel);
        if (old && old.length === st.size) continue;
        try { clearsnapLuaCache.set(rel, FS.readFile(path)); clearsnapLuaCacheFresh.add(rel); } catch (e) {}
    }
}
