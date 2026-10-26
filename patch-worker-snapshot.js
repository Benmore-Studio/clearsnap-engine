// ============ Clearsnap: snapshots and resume ============
// pdfTeX and XeTeX call Module.clearsnapPoint(kind, pages) at the top of their main loop once TeX has read past the
// main file's \begin{document} line (kind 0) and after each shipped page (kind 1) (busytex-build/patch-snapshot.py).
// There the worker copies TeX's memory and the job's files. The next compile of the document restores the latest copy
// whose input is unchanged (every file TeX had read by then, the main file up to where it had read, and the files it
// had found missing, and the preamble: the compiler's format key, which covers the preamble's text and the project
// files it reads, since a run on the preamble format reads neither) into a fresh engine and lets TeX carry on from
// there, so the preamble and the pages before an edit aren't typeset again. A resumed run that fails is done again in
// full, so errors always come from a full run.
const SNAP_ENGINE = { pdflatex: 'pdftex', xelatex: 'xetex' };
const SNAP_CHUNK = 65536;
const SNAP_KEEP = 8;
let clearsnapSnaps = [];     // the last compile's snapshots, oldest first
let clearsnapRunSnaps = [];  // the current run's

// The main file is compared with its preamble reduced to its line breaks, as a compile on the preamble format writes
// it (patch-worker.py), so snapshots carry over between compiles with and without the format. Positions in it are
// translated between the two layouts.
const SNAP_MAIN = '/document.tex';
const SNAP_BEGIN = new TextEncoder().encode('\\begin{document}');
function snapLayout(bytes) {
    let start = -1;
    for (let i = 0; start < 0 && i + SNAP_BEGIN.length <= bytes.length; i++) {
        let k = 0;
        while (k < SNAP_BEGIN.length && bytes[i + k] === SNAP_BEGIN[k]) k++;
        if (k === SNAP_BEGIN.length) start = i;
    }
    if (start < 0) return { bytes, start: 0, lines: 0 };
    let lines = 0;
    for (let i = 0; i < start; i++) if (bytes[i] === 10) lines++;
    const out = new Uint8Array(lines + bytes.length - start);
    out.fill(10, 0, lines);
    out.set(bytes.subarray(start), lines);
    return { bytes: out, start, lines };
}

function snapHash(bytes, end = bytes.length) {
    if (end > bytes.length) return 'short';
    let h = 0x811c9dc5 ^ end;
    for (let i = 0; i < end; i++) h = Math.imul(h ^ bytes[i], 16777619);
    return (h >>> 0).toString(36) + ':' + end;
}

function snapSame(a, b) {
    if (a.length !== b.length) return false;
    const n = a.length >> 2, x = new Uint32Array(a.buffer, a.byteOffset, n), y = new Uint32Array(b.buffer, b.byteOffset, n);
    for (let i = 0; i < n; i++) if (x[i] !== y[i]) return false;
    for (let i = n << 2; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
}

// What TeX reads, writes and finds missing outside TeX Live during a run.
function snapTrack(Module) {
    const FS = Module.FS, t = { on: true, busy: false, reads: new Map(), absent: new Set(), written: new Set() };
    const outside = p => !!p && !/^\/(texlive|dev|proc)\//.test(p) && !/\.fmt$/.test(p);
    const abs = p => Module.PATH.normalize(String(p).startsWith('/') ? String(p) : FS.cwd() + '/' + p);
    t.read = p => { t.busy = true; try { return FS.readFile(p); } finally { t.busy = false; } };
    t.content = p => p === SNAP_MAIN ? snapLayout(t.read(p)).bytes
        : p === '/document.aux' && t.auxNorm ? new TextEncoder().encode(t.auxNorm(new TextDecoder().decode(t.read(p)))) : t.read(p);
    const open = FS.open, lookupPath = FS.lookupPath;
    FS.open = function (path, flags, mode) {
        const st = open.call(FS, path, flags, mode);
        if (t.on && !t.busy && outside(st.path)) {
            if ((st.flags & 3) !== 0) t.written.add(st.path);
            else if (!t.reads.has(st.path) && !t.written.has(st.path)) t.reads.set(st.path, snapHash(t.content(st.path)));
        }
        return st;
    };
    // Every look for a file goes through lookupPath (open, stat, and access, which kpathsea checks files with).
    FS.lookupPath = function (path, opts) {
        try { return lookupPath.call(FS, path, opts); } catch (e) {
            if (t.on && !t.busy && e && e.errno === 44 && typeof path === 'string' && outside(abs(path))) t.absent.add(abs(path));
            throw e;
        }
    };
    return t;
}

function snapTake(Module, t, kind, pages, prev, mainpos, key, work) {
    const FS = Module.FS, heap = Module.HEAPU8, chunks = [];
    for (let i = 0, k = 0; i < heap.length; i += SNAP_CHUNK, k++) {
        const c = heap.subarray(i, Math.min(heap.length, i + SNAP_CHUNK)), p = prev && prev.memory[k];
        chunks.push(p && snapSame(p, c) ? p : c.slice());
    }
    const streams = [], prefix = {}, files = {};
    for (const s of FS.streams) {
        if (!s || !s.path || s.path.startsWith('/dev/') || (s.node && FS.isDir(s.node.mode))) continue;
        // The main file: where TeX's own reading has got to (stdio's read-ahead excluded), when the engine knows.
        let position = s.path === SNAP_MAIN && mainpos >= 0 ? mainpos : s.position;
        if (s.path === SNAP_MAIN) { const l = snapLayout(t.read(s.path)); position = Math.max(0, position - l.start) + l.lines; }
        streams.push({ fd: s.fd, path: s.path, flags: s.flags, position });
        if (t.reads.has(s.path) && (s.flags & 3) === 0) prefix[s.path] = snapHash(t.content(s.path), position);
    }
    for (const p of t.written) { try { files[p] = t.read(p); } catch (e) {} }
    return { kind, pages, key, work, memory: chunks, size: heap.length, sp: Module.asm.stackSave(), streams, files, prefix, exact: mainpos >= 0,
        reads: new Map(t.reads), absent: new Set(t.absent) };
}

// Whether the input a snapshot had read is still the same.
function snapValid(Module, t, snap, key) {
    if (!key || snap.key !== key) return false;
    for (const p of snap.absent) if (Module.FS.analyzePath(p).exists) return false;
    for (const [p, h] of snap.reads) {
        let d;
        try { d = t.content(p); } catch (e) { return false; }
        if (p in snap.prefix ? snapHash(d, Number(snap.prefix[p].split(':')[1])) !== snap.prefix[p] : snapHash(d) !== h) return false;
    }
    return true;
}

// Runs TeX with snapshot points, or resumes the latest snapshot this input allows. The result says which page it
// resumed after (clearsnapResumed) when it did.
// auxNorm: when the document prints no page numbers, the .aux is compared without them (as for reruns).
// key: the compiler's key for this preamble (clearsnapKey).
function snapRun(Module, engine, docSource, args, allowResume, auxNorm, key) {
    const e = SNAP_ENGINE[engine], asm = Module.asm;
    if (!e || !asm || !asm['clearsnap_' + e + '_setup']) return Module.callMainWithRedirects(args);
    const t = snapTrack(Module);
    t.auxNorm = auxNorm || null;
    let last = 0, every = 300, base = 0, runStart = performance.now();
    clearsnapRunSnaps = [];
    Module.clearsnapPoint = (kind, pages, mainpos) => {
        const now = performance.now();
        if (kind === 1 && now - last < every) return;
        clearsnapRunSnaps.push(snapTake(Module, t, kind, pages, clearsnapRunSnaps[clearsnapRunSnaps.length - 1], mainpos, key, base + now - runStart));
        last = performance.now();
        // Copies cost time: the next one waits at least 20 times as long as this one took (at most 5% of TeX's time).
        every = Math.max(every, 20 * (last - now));
        // Too many: keep the first and every other one after it, and space later ones further apart.
        if (clearsnapRunSnaps.length > SNAP_KEEP) { clearsnapRunSnaps = clearsnapRunSnaps.filter((s, i) => i === 0 || i % 2 === 1); every *= 2; }
    };
    const FS = Module.FS;
    let i = allowResume ? clearsnapSnaps.length - 1 : -1;
    while (i >= 0 && !(clearsnapSnaps[i].engine === engine && snapValid(Module, t, clearsnapSnaps[i], key))) i--;
    let r;
    if (i >= 0) {
        const snap = clearsnapSnaps[i];
        workerLog(`Resuming after ${snap.kind === 0 ? '\\begin{document}' : 'page ' + snap.pages}`);
        clearsnapRunSnaps = clearsnapSnaps.slice(0, i + 1);
        t.reads = new Map(snap.reads);
        t.absent = new Set(snap.absent);
        t.written = new Set(Object.keys(snap.files));
        for (const p of Object.keys(snap.prefix)) t.reads.set(p, snapHash(t.content(p)));
        let where = '', mainpos = -1;
        try {
            if (Module.HEAPU8.length < snap.size) asm['clearsnap_' + e + '_grow'](snap.size);
            const heap = Module.HEAPU8;
            snap.memory.forEach((c, k) => heap.set(c, k * SNAP_CHUNK));
            t.busy = true;
            for (const [p, d] of Object.entries(snap.files)) { where = p; FS.writeFile(p, d); }
            for (const s of snap.streams) {
                where = s.path;
                if (FS.streams[s.fd]) FS.closeStream(s.fd);
                const st = FS.open(s.path, s.flags & ~(64 | 128 | 512));
                if (st.fd !== s.fd) { FS.closeStream(st.fd); FS.createStream(st, s.fd); }
                if (s.path === SNAP_MAIN) {
                    const l = snapLayout(t.read(s.path));
                    FS.streams[s.fd].position = s.position - l.lines + l.start;
                    if (snap.exact) mainpos = FS.streams[s.fd].position;
                }
                else FS.streams[s.fd].position = s.position;
            }
            t.busy = false;
            asm.stackRestore(snap.sp);
            base = snap.work || 0;
            runStart = performance.now();
            r = Module.callWithRedirects(() => asm['clearsnap_' + e + '_resume'](mainpos));
        } catch (err) {
            workerLog(`Snapshot restore failed at ${where}: ${err.message || err}`);
            r = { exit_code: 1, stdout: '', stderr: '' };
        }
        r.clearsnapResumed = snap.kind === 0 ? 0 : snap.pages;
    } else {
        const begin = docSource.indexOf('\\begin{document}');
        asm['clearsnap_' + e + '_setup'](1, begin < 0 ? 0 : docSource.slice(0, begin).split('\n').length);
        runStart = performance.now();
        r = Module.callMainWithRedirects(args);
    }
    t.on = false;
    for (const s of clearsnapRunSnaps) s.engine ||= engine;
    return r;
}

// ---- Kept across visits ----
// Snapshots that saved real work (SNAP_STORE_WORK of TeX's time) are kept in the origin's private file system: memory in
// 64 KB chunks named by their SHA-256 (shared between snapshots, compiles and documents, so a save writes only what
// changed), stored deflated (TeX's memory shrinks about sixfold), all-zero chunks not stored at all, and a manifest
// per document key. A save starts once the worker has been idle for a moment after a compile,
// and stops when the next compile starts. A compile with no snapshot in memory for its key reads its manifest first.
const SNAP_STORE = 'clearsnap-snapshots-2';
const SNAP_STORE_WORK = 800;
const SNAP_STORE_KEEP = 4;
let snapStoreGen = 0;
const snapIds = new WeakMap();

// Runs fn over items, n at a time (the private file system is far faster with many reads or writes in flight).
async function snapEach(items, n, fn) {
    let next = 0;
    await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => { while (next < items.length) await fn(items[next++]); }));
}

async function snapStoreDir() {
    let h = 0;
    for (const c of String(busytexJsUrl || '')) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
    const root = await navigator.storage.getDirectory();
    return root.getDirectoryHandle(SNAP_STORE + '-' + (h >>> 0).toString(36), { create: true });
}

function snapZero(bytes) {
    if (bytes.byteOffset % 4 || bytes.length % 4) return false;
    const w = new Uint32Array(bytes.buffer, bytes.byteOffset, bytes.length >> 2);
    for (let i = 0; i < w.length; i++) if (w[i]) return false;
    return true;
}

const snapPack = bytes => new Response(new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate-raw'))).arrayBuffer();
const snapUnpack = blob => new Response(blob.stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer();

async function snapId(bytes) {
    let id = snapIds.get(bytes);
    if (!id && snapZero(bytes)) id = 'zero-' + bytes.length;
    if (!id) {
        const d = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
        id = Array.from(d.subarray(0, 16), b => b.toString(16).padStart(2, '0')).join('');
        snapIds.set(bytes, id);
    }
    return id;
}

async function snapManifestName(key) {
    return (await snapId(new TextEncoder().encode(key))) + '.json';
}

function snapStoreLater(key, snaps) {
    const gen = ++snapStoreGen;
    if (!key || !snaps.some(s => s.work >= SNAP_STORE_WORK)) return;
    setTimeout(() => snapSave(gen, key, snaps).catch(e => workerLog('Snapshots not saved: ' + (e.message || e))), 1500);
}

async function snapSave(gen, key, snaps) {
    if (gen !== snapStoreGen || !self.navigator?.storage?.getDirectory) return;
    const t0 = performance.now();
    const dir = await snapStoreDir(), chunks = await dir.getDirectoryHandle('chunks', { create: true });
    const have = new Set();
    for await (const name of chunks.keys()) have.add(name);
    let wrote = 0;
    const put = async bytes => {
        const id = await snapId(bytes);
        if (!have.has(id) && !id.startsWith('zero-')) {
            have.add(id);
            const packed = await snapPack(bytes);
            const w = await (await chunks.getFileHandle(id, { create: true })).createWritable();
            await w.write(packed);
            await w.close();
            wrote += packed.byteLength;
        }
        return id;
    };
    const out = [];
    for (const s of snaps.filter(s => s.work >= SNAP_STORE_WORK)) {
        const memory = new Array(s.memory.length), files = {};
        await snapEach(s.memory.map((c, k) => k), 16, async k => { if (gen === snapStoreGen) memory[k] = await put(s.memory[k]); });
        if (gen !== snapStoreGen) return;
        for (const [p, d] of Object.entries(s.files)) files[p] = await put(d);
        out.push({ kind: s.kind, pages: s.pages, key: s.key, work: s.work, size: s.size, sp: s.sp, streams: s.streams,
            prefix: s.prefix, exact: s.exact, engine: s.engine, reads: [...s.reads], absent: [...s.absent], memory, files });
    }
    if (gen !== snapStoreGen) return;
    const w = await (await dir.getFileHandle(await snapManifestName(key), { create: true })).createWritable();
    await w.write(JSON.stringify({ key, saved: Date.now(), snaps: out }));
    await w.close();
    // Keep the newest manifests, and the chunks they use.
    const manifests = [];
    for await (const [name, h] of dir.entries()) {
        if (!name.endsWith('.json')) continue;
        try { manifests.push({ name, m: JSON.parse(await (await h.getFile()).text()) }); } catch (e) { await dir.removeEntry(name).catch(() => {}); }
    }
    manifests.sort((a, b) => b.m.saved - a.m.saved);
    for (const { name } of manifests.slice(SNAP_STORE_KEEP)) await dir.removeEntry(name).catch(() => {});
    const used = new Set();
    for (const { m } of manifests.slice(0, SNAP_STORE_KEEP)) for (const s of m.snaps) { s.memory.forEach(id => used.add(id)); Object.values(s.files).forEach(id => used.add(id)); }
    for (const id of have) if (!used.has(id) && !id.startsWith('zero-')) await chunks.removeEntry(id).catch(() => {});
    workerLog(`Snapshots saved: ${out.length}, ${(wrote / 1048576).toFixed(1)}MB written in ${Math.round(performance.now() - t0)}ms`);
}

// The document's kept snapshots, when none for its key are in memory.
async function snapFromStore(key) {
    snapStoreGen++;
    if (!key || clearsnapSnaps.some(s => s.key === key) || !self.navigator?.storage?.getDirectory) return;
    try {
        const t0 = performance.now();
        const dir = await snapStoreDir();
        let m;
        try { m = JSON.parse(await (await (await dir.getFileHandle(await snapManifestName(key))).getFile()).text()); } catch (e) { return; }
        if (m.key !== key || !m.snaps.length) return;
        const chunks = await dir.getDirectoryHandle('chunks'), cache = new Map();
        const ids = [...new Set(m.snaps.flatMap(s => [...s.memory, ...Object.values(s.files)]))];
        await snapEach(ids, 32, async id => {
            cache.set(id, id.startsWith('zero-') ? new Uint8Array(Number(id.slice(5))) : new Uint8Array(await snapUnpack(await (await chunks.getFileHandle(id)).getFile())));
        });
        const snaps = m.snaps.map(s => ({ ...s, reads: new Map(s.reads), absent: new Set(s.absent), memory: s.memory.map(id => cache.get(id)),
            files: Object.fromEntries(Object.entries(s.files).map(([p, id]) => [p, cache.get(id)])) }));
        clearsnapSnaps = snaps;
        const bytes = [...cache.values()].reduce((n, c) => n + c.length, 0);
        workerLog(`Snapshots read: ${snaps.length}, ${(bytes / 1048576).toFixed(1)}MB in ${Math.round(performance.now() - t0)}ms`);
    } catch (e) {
        workerLog('Snapshots not read: ' + (e.message || e));
    }
}

