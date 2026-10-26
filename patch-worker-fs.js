// ============ Clearsnap: a faster file system for TeX's file searches ============
// kpathsea looks the same paths up again and again: every candidate directory and extension for every file it opens,
// readable-file checks, and case-insensitive matches found by listing whole directories. Each look is path resolution
// in JavaScript, which took a fifth to a quarter of a text or LuaLaTeX compile (engine/research/README.md). TeX Live's
// files don't change while TeX runs (they are mounted before it starts; only luaotfload writes, under texmf-var), and
// the project's change only when a file is created, removed or renamed, so while a run lasts lookups and directory
// listings are remembered, misses included, and forgotten whenever a file appears, goes or moves. Opening a file also
// scanned every file descriptor from 0 for a free one; the search now starts after the last one handed out.
function clearsnapFastFS(Module) {
    const FS = Module.FS;
    const cacheable = p => !/^\/(dev|proc)\//.test(p) && !p.includes('/texmf-var/') && !p.includes('/../');
    let on = false, lookups = new Map(), listings = new Map();
    const lookupPath = FS.lookupPath, readdir = FS.readdir;
    FS.lookupPath = function (path, opts = {}) {
        if (!on || typeof path !== 'string' || opts.recurse_count) return lookupPath.call(FS, path, opts);
        const full = path.startsWith('/') ? path : FS.cwd() + '/' + path;
        if (!cacheable(full)) return lookupPath.call(FS, path, opts);
        const key = full + '|' + (opts.parent ? 1 : 0) + (opts.follow ? 1 : 0) + (opts.follow_mount === false ? 0 : 1);
        let hit = lookups.get(key);
        if (!hit) {
            try { hit = { r: lookupPath.call(FS, path, opts) }; } catch (e) { hit = { e }; }
            lookups.set(key, hit);
        }
        if (hit.e) throw hit.e;
        return hit.r;
    };
    FS.readdir = function (path) {
        if (!on || typeof path !== 'string' || !path.startsWith('/') || !cacheable(path)) return readdir.call(FS, path);
        let names = listings.get(path);
        if (!names) { names = readdir.call(FS, path); listings.set(path, names); }
        return names;
    };
    for (const op of ['mknod', 'create', 'mkdir', 'symlink', 'unlink', 'rmdir', 'rename']) {
        const f = FS[op];
        FS[op] = function () {
            if (!on) return f.apply(FS, arguments);
            lookups = new Map(); listings = new Map();
            try { return f.apply(FS, arguments); } finally { lookups = new Map(); listings = new Map(); }
        };
    }
    let hint = 0;
    const nextfd = FS.nextfd, closeStream = FS.closeStream;
    FS.nextfd = function () {
        for (let fd = hint; fd <= FS.MAX_OPEN_FDS; fd++) if (!FS.streams[fd]) { hint = fd + 1; return fd; }
        return nextfd.call(FS);
    };
    FS.closeStream = function (fd) {
        closeStream.call(FS, fd);
        if (fd < hint) hint = fd;
    };
    // On for a run of TeX (and cleared), off between runs, when the worker mounts files.
    Module.clearsnapFastFS = state => { on = state; lookups = new Map(); listings = new Map(); };
}

