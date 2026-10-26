# Copies Siglum's compiler-side sources to build/siglum and patches its package fetcher so the engine can load any
# TeX Live 2025 package on demand from our static mirror (make-texlive.py). Fails loudly if upstream changes shape.
#   python3 patch-siglum.py
import os, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
SRC, OUT = os.path.join(HERE, 'node_modules/@siglum/engine/src'), os.path.join(HERE, 'build/siglum')
shutil.rmtree(OUT, ignore_errors=True)
shutil.copytree(SRC, OUT)
p = os.path.join(OUT, 'ctan.js')
s = open(p).read()

def sub(a, b, what):
    global s
    assert s.count(a) == 1, f'ctan.js: {what} not found'
    s = s.replace(a, b)

# 1) Look a missing name up as given and with every run-time extension (babel .ldf, fonts, biblatex styles...).
sub("const LATEX_FILE_EXTENSIONS = ['.sty', '.cls', '.def', '.clo', '.fd', '.cfg', '.tex'];",
    "const LATEX_FILE_EXTENSIONS = ['', '.sty', '.cls', '.def', '.clo', '.fd', '.cfg', '.tex', '.ldf', '.code.tex', '.tfm', '.pfb', '.vf', '.otf', '.ttf', '.enc', '.map', '.bbx', '.cbx', '.lbx', '.dbx', '.bst', '.lua', '.ini'];",
    'extension list')
# 2) Our archives are gzipped tars, which the browser decompresses natively (no xz library to load).
sub("            const XzStream = await loadXzwasm();\n            const xzStream = new XzStream(new Blob([xzData]).stream());",
    "            const xzStream = new Blob([xzData]).stream().pipeThrough(new DecompressionStream('gzip'));",
    'xz decompression')
# 3) Mount every run-time file of a package (upstream kept only .sty/.cls/... and Type 1 fonts, dropping babel
#    languages, biblatex styles, OpenType fonts and Lua files).
sub("                if (texExtensions.includes(ext) || fontExtensions.includes(ext)) {",
    "                if (texExtensions.includes(ext) || fontExtensions.includes(ext) || !tarPath.endsWith('/')) {",
    'mount filter')
# 4) Fetch packages in parallel (upstream ran one at a time because its xz decoder couldn't run concurrently).
sub("        const { concurrency = 1 } = options;", "        const { concurrency = 8 } = options;", 'batch concurrency')
# 4b) A font fontspec asks for by name (\setmainfont{TeX Gyre Pagella}) isn't a file name: look it up in the mirror's
#     font-names.json (make-font-names.py) to find its package.
sub("""    async lookupPackageForFile(fileName) {
        const index = await this.loadFileToPackageIndex();
        return index[fileName] || null;
    }
""", """    async lookupPackageForFile(fileName) {
        const index = await this.loadFileToPackageIndex();
        return index[fileName] || (await this.lookupPackageForFontName(fileName));
    }

    async lookupPackageForFontName(name) {
        if (!this.fontNamesLoading) {
            this.fontNamesLoading = fetch(`${this.bundlesUrl}/font-names.json`).then(r => (r.ok ? r.json() : {})).catch(() => ({}));
        }
        const names = await this.fontNamesLoading;
        const key = String(name).replace(/^(name|file):/, '').split(/[/:(]/)[0].replace(/\\.(sty|otf|ttf|ttc)$/i, '').toLowerCase().replace(/[^a-z0-9]/g, '');
        return (key && names[key]) || null;
    }
""", 'font names')
open(p, 'w').write(s)
# 5) A cached per-preamble format is a pdfLaTeX-only thing here (upstream would run pdflatex on LuaLaTeX preambles).
p = os.path.join(OUT, 'compiler.js')
s = open(p).read()
sub("                        if (!cachedFormat && preamble && engine !== 'xelatex') {", "                        if (!cachedFormat && preamble && engine === 'pdflatex' && this._formatAllowed(fmtKey, options)) {", 'format generation guard')
# 6) Some documents crash the WebAssembly TeX ("memory access out of bounds") when they run on their cached preamble
#    format, though they compile fine without it (seen with a large TikZ/pgfplots preamble plus heavy drawings). Such a
#    compile is redone without the format, and the format stays off for that preamble, remembered across visits.
sub("    async compile(source, options = {}) {\n", """    _formatAllowed(key, options = {}) {
        if (options.clearsnapNoFormat) return false;
        if (!this._badFormats) {
            try { this._badFormats = new Set(JSON.parse(localStorage.getItem('clearsnap-bad-formats') || '[]')); } catch (e) { this._badFormats = new Set(); }
        }
        return !this._badFormats.has(key);
    }

    _markBadFormat(key) {
        this._formatAllowed(key);
        this._badFormats.add(key);
        if (this._fmtMemCache?.key === key) this._fmtMemCache = null;
        try { localStorage.setItem('clearsnap-bad-formats', JSON.stringify([...this._badFormats].slice(-200))); } catch (e) {}
    }

    async compile(source, options = {}) {
""", 'compile method')
sub("        if (this._fmtMemCache?.key === fmtKey && this._fmtMemCache?.data?.buffer?.byteLength > 0) {",
    "        if (this._formatAllowed(fmtKey, options) && this._fmtMemCache?.key === fmtKey && this._fmtMemCache?.data?.buffer?.byteLength > 0) {",
    'format memory cache')
sub("        } else {\n            // Fall back to filesystem cache", "        } else if (this._formatAllowed(fmtKey, options)) {\n            // Fall back to filesystem cache", 'format filesystem cache')
sub("""                    } else {
                        resolve({
                            success: false,""", """                    } else if (cachedFormat && /memory access out of bounds|RuntimeError|unreachable|Aborted\\(/i.test(String(result.error || ''))) {
                        this._log('Cached format crashed the engine; compiling without it');
                        this._markBadFormat(fmtKey);
                        // Next tick: the message handler clears pendingCompile right after this callback returns.
                        await new Promise(r => setTimeout(r, 0));
                        this.compile(source, { ...options, clearsnapNoFormat: true }).then(resolve, reject);
                    } else {
                        resolve({
                            success: false,""", 'compile failure branch')
# 7) Cross-references from the previous compile carry over when the format state changed between compiles (the first
#    compile of a preamble has no format, the next one does), so the next compile doesn't start with every \ref undefined.
sub("        const auxCache = await getAuxCache(auxCacheKey);",
    "        const auxCache = (await getAuxCache(auxCacheKey)) || (cachedFormat ? await getAuxCache(preambleHash) : null);",
    'aux cache lookup')
# 8) Heavy documents (dozens of TikZ pictures, two or three passes) need more than two minutes on the first compile.
sub("                    reject(new Error('Compilation timeout'));\n                }\n            }, 120000);",
    "                    reject(new Error('Compilation timeout'));\n                }\n            }, 300000);",
    'compile timeout')
# 9) Tell the editor when packages are being fetched (the slow part of a document's first compile on a device).
sub("                const { fetched, failed, skipped } = await this.ctanFetcher.batchFetchPackages(ctanPackages);",
    "                this.onProgress('fetch', String(ctanPackages.length));\n                const { fetched, failed, skipped } = await this.ctanFetcher.batchFetchPackages(ctanPackages);",
    'prefetch progress')
# 10) Cached preamble formats and cross-reference (.aux) caches carry an engine revision in their key. They were keyed
#     by the preamble alone, so a browser kept using ones built by an older engine (other shims, other package files).
s = s.replace("        const fmtKey = preambleHash + '_' + engine;\n", "        const fmtKey = preambleHash + '_' + engine + CLEARSNAP_CACHE_REV;\n")
assert s.count("+ engine + CLEARSNAP_CACHE_REV;") == 2, 'compiler.js: format keys not found'
sub("        const auxCacheKey = cachedFormat ? preambleHash + '_fmt' : preambleHash;\n        const auxCache = (await getAuxCache(auxCacheKey)) || (cachedFormat ? await getAuxCache(preambleHash) : null);",
    "        const auxCacheKey = (cachedFormat ? preambleHash + '_fmt' : preambleHash) + CLEARSNAP_CACHE_REV;\n        const auxCache = options.clearsnapNoAux ? null : (await getAuxCache(auxCacheKey)) || (cachedFormat ? await getAuxCache(preambleHash + CLEARSNAP_CACHE_REV) : null);",
    'aux cache key')
# 11) A compile that fails in the preamble (or at \begin{document}) while using cached state is done once more from
#     scratch before its error is shown, so a stale cache can never produce an error a clean compile wouldn't.
sub("                    } else {\n                        resolve({\n                            success: false,",
    "                    } else if ((cachedFormat || auxCache) && !options.clearsnapClean && clearsnapPreambleFailure(result.log, source)) {\n"
    "                        this._log('Compile failed before the document began while using cached state; compiling again from scratch');\n"
    "                        await new Promise(r => setTimeout(r, 0));\n"
    "                        this.compile(source, { ...options, clearsnapNoFormat: true, clearsnapNoAux: true, clearsnapClean: true }).then(r => {\n"
    "                            if (r.success && cachedFormat) this._markBadFormat(fmtKey);\n"
    "                            resolve(r);\n"
    "                        }, reject);\n"
    "                    } else {\n                        resolve({\n                            success: false,",
    'clean retry branch')
sub("export class SiglumCompiler", open(os.path.join(HERE, 'patch-shared.js')).read() + open(os.path.join(HERE, 'patch-siglum-helpers.js')).read() + "export class SiglumCompiler", 'class anchor')
# 12) The figure cache: pictures the worker cached are kept in the browser's storage and sent back with each compile.
sub("    _formatAllowed(key, options = {}) {\n", """    async _memoFor(preambleHash) {
        this._memo ||= new Map();
        let names = [];
        try { names = JSON.parse(localStorage.getItem('clearsnap-memo:' + preambleHash) || '[]'); } catch (e) {}
        const out = {};
        for (const n of names) {
            let d = this._memo.get(n);
            if (!d && await ensureMemoMount()) {
                d = await fileSystem.readBinary('/memo-cache/' + n).catch(() => null);
                if (d) this._memo.set(n, d);
            }
            if (d) out[n] = d;
        }
        return out;
    }

    _keepMemo(preambleHash, files, names) {
        this._memo ||= new Map();
        for (const [n, d] of Object.entries(files || {})) {
            this._memo.set(n, d);
            ensureMemoMount().then(ok => ok && fileSystem.writeBinary('/memo-cache/' + n, d, { createParents: true })).catch(() => {});
        }
        if (names) { try { localStorage.setItem('clearsnap-memo:' + preambleHash, JSON.stringify(names)); } catch (e) {} }
    }

    _noMemo(preambleHash) {
        try { return JSON.parse(localStorage.getItem('clearsnap-no-memoize') || '[]').includes(preambleHash); } catch (e) { return false; }
    }

    _markNoMemo(preambleHash) {
        try {
            const list = JSON.parse(localStorage.getItem('clearsnap-no-memoize') || '[]');
            if (!list.includes(preambleHash)) localStorage.setItem('clearsnap-no-memoize', JSON.stringify([...list, preambleHash].slice(-200)));
        } catch (e) {}
    }

    _formatAllowed(key, options = {}) {
""", 'memo methods')
sub("        // Send compile request\n", "        const memoFiles = await this._memoFor(preambleHash);\n\n        // Send compile request\n", 'memo lookup')
sub("""                    maxRetries: this.maxRetries,
                    verbose: this.verbose,
                },
                bundleData,
                ctanFiles,
                cachedFormat,
                cachedAuxFiles: auxCache?.files || null,
""", """                    maxRetries: this.maxRetries,
                    verbose: this.verbose,
                    noMemoize: this._noMemo(preambleHash),
                    memoFormat: clearsnapMemoFormat,
                    clearsnapKey: fmtKey,
                },
                bundleData,
                ctanFiles,
                cachedFormat,
                cachedAuxFiles: auxCache?.files || null,
                cachedMemoFiles: memoFiles,
""", 'compile message')
sub("""                        if (result.auxFilesToCache) {
                            await saveAuxCache(auxCacheKey, result.auxFilesToCache);
                        }
""", """                        if (result.auxFilesToCache) {
                            await saveAuxCache(auxCacheKey, result.auxFilesToCache);
                        }
                        if (result.memoFiles || result.memoNames) this._keepMemo(preambleHash, result.memoFiles, result.memoNames);
""", 'memo keep')
sub("                        if (!cachedFormat && preamble && engine === 'pdflatex' && this._formatAllowed(fmtKey, options)) {",
    "                        if (!cachedFormat && preamble && engine === 'pdflatex' && this._formatAllowed(fmtKey, options) && (result.memoize || 'off') === (clearsnapMemoFormat ? 'inject' : 'off')) {",
    'format skip with figure cache')
sub("                resolve: async (result) => {\n                    clearTimeout(timeout);\n",
    "                resolve: async (result) => {\n                    clearTimeout(timeout);\n                    if (result.memoize === 'failed') this._markNoMemo(preambleHash);\n",
    'memo failure mark')
# 13) Formats see the project's files (a preamble can load the project's own class or package, or \input a file), and
#     the format's key includes those files. A format TeX refuses or fails to build stays off for that preamble instead
#     of being built again after every compile. With the figure cache on, the format is built with memoize loaded and
#     keyed apart, and the worker is told which kind it got.
sub("        const fmtKey = preambleHash + '_' + engine + CLEARSNAP_CACHE_REV;\n\n        // Check in-memory cache first",
    "        // With the figure cache on, the format has memoize loaded, so it is keyed apart.\n"
    "        const clearsnapMemoFormat = memoMode(source + projectTexSource(ctanFiles), { noMemoize: this._noMemo(preambleHash) }) === 'inject';\n"
    "        const fmtKey = preambleHash + preambleFilesKey(preamble, options.additionalFiles) + (clearsnapMemoFormat ? '_mmz' : '') + '_' + engine + CLEARSNAP_CACHE_REV;\n\n        // Check in-memory cache first",
    'compile format key')
sub("        const fmtKey = preambleHash + '_' + engine + CLEARSNAP_CACHE_REV;\n        const fmtPath",
    "        const fmtKey = preambleHash + preambleFilesKey(preamble, options.additionalFiles) + (options.memoize ? '_mmz' : '') + '_' + engine + CLEARSNAP_CACHE_REV;\n        const fmtPath",
    'generateFormat format key')
sub("        // Get CTAN files from memory cache\n        const ctanFiles = this.ctanFetcher.getCachedFiles();\n\n        this._log('Generating format file...');",
    "        // Get CTAN files from memory cache\n        const ctanFiles = this.ctanFetcher.getCachedFiles();\n"
    "        for (const [filename, content] of Object.entries(options.additionalFiles || {})) {\n"
    "            ctanFiles['/' + filename] = typeof content === 'string' ? new TextEncoder().encode(content) : content;\n"
    "        }\n\n        this._log('Generating format file...');",
    'generateFormat project files')
sub("                            this.generateFormat(source, { engine }).then(async () => {",
    "                            this.generateFormat(source, { engine, additionalFiles: options.additionalFiles, memoize: clearsnapMemoFormat }).then(async () => {",
    'format generation files')
sub("                            }).catch(() => {}); // Silent fail for background task",
    "                            }).catch(e => { if (e && e.clearsnapFailed) this._markBadFormat(fmtKey); });",
    'format failure mark')
sub("                        reject(new Error(result.error || 'Format generation failed'));",
    "                        reject(Object.assign(new Error(result.error || 'Format generation failed'), { clearsnapFailed: true }));",
    'format failure flag')
sub("                type: 'generate-format',\n                id: crypto.randomUUID(),\n",
    "                type: 'generate-format',\n                id: crypto.randomUUID(),\n                memoize: !!options.memoize,\n", 'format request memoize')
# 14) A document's packages that only other packages load (memoize's advice, fonts, the chess font, unicode-math's
#     amsmath...) were found one TeX restart at a time on every compile, though they sat in the browser's cache. The
#     packages and bundles a preamble's compiles asked for are remembered and loaded before TeX starts, and so are the
#     figure cache's own packages when the document has drawings.
sub("    async _memoFor(preambleHash) {\n", """    _needsFor(source, kind = '') {
        try { return JSON.parse(localStorage.getItem('clearsnap-needs' + kind + ':' + hashPreamble(extractPreamble(source) || '')) || '[]'); } catch (e) { return []; }
    }

    _keepNeeds(source) {
        for (const [kind, asked] of [['', this._clearsnapAsked], ['-bundles', this._clearsnapAskedBundles]]) {
            if (!asked || !asked.size) continue;
            const all = [...new Set([...this._needsFor(source, kind), ...asked])].slice(-150);
            try { localStorage.setItem('clearsnap-needs' + kind + ':' + hashPreamble(extractPreamble(source) || ''), JSON.stringify(all)); } catch (e) {}
        }
    }

    async _memoFor(preambleHash) {
""", 'needs methods')
sub("            this._log(`[CTAN-REQ] Worker requested package: ${actualPackage}${yearLabel}`);\n",
    "            this._log(`[CTAN-REQ] Worker requested package: ${actualPackage}${yearLabel}`);\n"
    "            if (!tlYear && this._clearsnapAsked) this._clearsnapAsked.add(actualPackage);\n", 'needs record')
sub("            const { ctanPackages, additionalBundles } = this.bundleManager.prescanForCtanPackages(source, engine, additionalFilesMap);\n",
    "            const { ctanPackages: clearsnapScanned, additionalBundles } = this.bundleManager.prescanForCtanPackages(source, engine, additionalFilesMap);\n"
    "            const clearsnapMemoPkgs = MEMO_DRAWINGS.test(source + projectTexSource(additionalFilesMap)) ? ['memoize', 'advice', 'collargs'] : [];\n"
    "            const ctanPackages = [...new Set([...clearsnapScanned, ...clearsnapMemoPkgs, ...(engine === 'lualatex' ? LUALATEX_PACKAGES : []), ...this._needsFor(source)])];\n"
    "            this._clearsnapAsked = new Set();\n", 'needs prefetch')
sub("                resolve: async (result) => {\n                    clearTimeout(timeout);\n                    if (result.memoize === 'failed') this._markNoMemo(preambleHash);\n",
    "                resolve: async (result) => {\n                    clearTimeout(timeout);\n                    if (result.memoize === 'failed') this._markNoMemo(preambleHash);\n                    this._keepNeeds(source);\n", 'needs keep')
# 15) LuaLaTeX: the prebuilt LuaLaTeX format bundle doesn't load in wasm32 and the LuaTeX packages bundle is older than
#     TeX Live 2025 (luaotfload 3.23), so neither is loaded; what building the format reads comes with every LuaLaTeX
#     compile instead, LuaTeX packages from the mirror (LUALATEX_BUNDLES/PACKAGES in patch-siglum-helpers.js). The
#     format the worker builds on the first LuaLaTeX compile, and luaotfload's font database and parsed fonts, are kept
#     in memory and in the browser's storage, and sent with each LuaLaTeX compile.
sub("        const { bundles } = this.bundleManager.checkPackages(source, engine);\n\n        // Add eager bundles for this engine",
    "        let { bundles } = this.bundleManager.checkPackages(source, engine);\n"
    "        if (engine === 'lualatex') bundles = [...bundles, ...LUALATEX_BUNDLES];\n"
    "        bundles = [...bundles, ...this._needsFor(source, '-bundles').filter(b => this.bundleManager.bundleExists(b))];\n"
    "        this._clearsnapAskedBundles = new Set();\n\n        // Add eager bundles for this engine", 'LuaLaTeX bundles')
sub("        const allBundles = [...new Set([...bundles, ...eagerBundles, ...depBundles])];\n",
    "        const allBundles = [...new Set([...bundles, ...eagerBundles, ...depBundles])].filter(b => engine !== 'lualatex' || !LUALATEX_SKIP.includes(b));\n", 'LuaLaTeX bundle skip')
sub("            this._log('Worker requested bundle: ' + bundleName);\n",
    "            this._log('Worker requested bundle: ' + bundleName);\n            if (this._clearsnapAskedBundles) this._clearsnapAskedBundles.add(bundleName);\n", 'needs bundles record')
sub("    async _memoFor(preambleHash) {\n", """    async _luaFormat() {
        if (this._luaFmt) return this._luaFmt;
        await ensureFmtCacheMount();
        const data = await fileSystem.readBinary('/' + getFmtPath('lualatex' + CLEARSNAP_CACHE_REV)).catch(() => null);
        if (data && data.byteLength > 0) this._luaFmt = new Uint8Array(data);
        return this._luaFmt || null;
    }

    // luaotfload's font database and parsed fonts, kept in the browser's storage (paths listed in localStorage).
    async _luaCache() {
        if (this._luaCacheFiles) return this._luaCacheFiles;
        const files = {};
        let names = [];
        try { names = JSON.parse(localStorage.getItem('clearsnap-lua-cache' + CLEARSNAP_CACHE_REV) || '[]'); } catch (e) {}
        if (names.length && await ensureMemoMount()) {
            for (const n of names) {
                const d = await fileSystem.readBinary('/memo-cache/luatex-cache/' + n).catch(() => null);
                if (d) files[n] = new Uint8Array(d);
            }
        }
        this._luaCacheFiles = files;
        return files;
    }

    _keepLuaCache(fresh) {
        const files = this._luaCacheFiles ||= {};
        for (const [n, d] of Object.entries(fresh)) {
            files[n] = d;
            ensureMemoMount().then(ok => ok && fileSystem.writeBinary('/memo-cache/luatex-cache/' + n, d, { createParents: true })).catch(() => {});
        }
        try { localStorage.setItem('clearsnap-lua-cache' + CLEARSNAP_CACHE_REV, JSON.stringify(Object.keys(files))); } catch (e) {}
    }

    _keepLuaFormat(data) {
        this._luaFmt = new Uint8Array(data);
        ensureFmtCacheMount()
            .then(() => fileSystem.writeBinary('/' + getFmtPath('lualatex' + CLEARSNAP_CACHE_REV), this._luaFmt, { createParents: true }))
            .catch(() => {});
    }

    async _memoFor(preambleHash) {
""", 'LuaLaTeX format methods')
sub("        const memoFiles = await this._memoFor(preambleHash);\n",
    "        const memoFiles = await this._memoFor(preambleHash);\n        const luaFormat = engine === 'lualatex' ? await this._luaFormat() : null;\n        const luaCache = engine === 'lualatex' ? await this._luaCache() : null;\n", 'LuaLaTeX format lookup')
sub("                cachedMemoFiles: memoFiles,\n", "                cachedMemoFiles: memoFiles,\n                cachedLuaFormat: luaFormat,\n                cachedLuaCache: luaCache,\n", 'LuaLaTeX format message')
sub("                    this._keepNeeds(source);\n", "                    this._keepNeeds(source);\n                    if (result.luaFormat) this._keepLuaFormat(result.luaFormat);\n                    if (result.luaCache) this._keepLuaCache(result.luaCache);\n", 'LuaLaTeX format keep')
# Start downloading the pdfLaTeX bundles as soon as the manifests are in, alongside the WebAssembly, not after it.
sub("""        await Promise.all([
            this._loadManifests(),
            this._loadWasm(),
        ]);

        // Worker init (required) + bundle preload (optional, don't fail if it errors)
        await Promise.all([
            this._initWorker(),
            this.bundleManager.preloadEngine('pdflatex').catch(e => {
                this._log('Bundle preload failed (will load on demand): ' + e.message);
            }),
        ]);
""", """        let preload = null;
        await Promise.all([
            this._loadManifests().then(() => {
                preload = this.bundleManager.preloadEngine('pdflatex').catch(e => {
                    this._log('Bundle preload failed (will load on demand): ' + e.message);
                });
            }),
            this._loadWasm(),
        ]);

        // Worker init (required) + bundle preload (optional, don't fail if it errors)
        await Promise.all([this._initWorker(), preload]);
""", 'init order')
open(p, 'w').write(s)
# 6) Bundle set v5 (make-bundles-v5.py) rebuilt some bundles without their documentation, at new offsets: a bundle
#    kept from v3 under the same name would be read wrongly, so the browser's bundle cache starts over once.
p = os.path.join(OUT, 'storage.js')
s = open(p).read()
sub('const BUNDLE_CACHE_VERSION = 4;', 'const BUNDLE_CACHE_VERSION = 5;', 'bundle cache version')
# 7) The compiled engine kept in the browser belongs to the address it came from. Upstream stored it under one fixed
#    name, so after the engine moved to /v4/ every returning browser kept starting the old binary with the new glue
#    code (LinkError: "invoke_vidd" ...) and never compiled. The version bump drops the old copies once.
# 8) Cached bundles belong to the bundle set they came from. Upstream's version bump never cleared them: it removed
#    the mount point itself, which the file system refuses, and the error was swallowed. So after v5 rebuilt some
#    bundles at new offsets, a browser that had v3's copies read garbage (a document with a long
#    preamble: "Missing \begin{document}" in etoolbox.sty). Each cached bundle now records its source, the bump clears the folder that holds them, and a
#    bundle cached from another set is fetched again.
sub("""                await fs.rmdir('/bundle-cache', { recursive: true });
                await fs.mountAuto('/bundle-cache');""", """                await fs.rmdir('/bundle-cache/bundles', { recursive: true }).catch(() => {});""", 'bundle cache clear')
sub('export async function getBundleFromCache(bundleName) {', 'export async function getBundleFromCache(bundleName, src) {', 'bundle cache get')
sub("""        const data = await fs.readBinary(`/bundle-cache/bundles/${bundleName}.data`);
        return data?.buffer || null;""", """        if (src && (await fs.readFile(`/bundle-cache/bundles/${bundleName}.src`).catch(() => '')) !== src) return null;
        const data = await fs.readBinary(`/bundle-cache/bundles/${bundleName}.data`);
        return data?.buffer || null;""", 'bundle cache source check')
sub('export async function saveBundleToCache(bundleName, data) {', 'export async function saveBundleToCache(bundleName, data, src) {', 'bundle cache save')
sub("""        await fs.writeBinary(`/bundle-cache/bundles/${bundleName}.data`, new Uint8Array(buffer));""", """        await fs.writeBinary(`/bundle-cache/bundles/${bundleName}.data`, new Uint8Array(buffer));
        if (src) await fs.writeFile(`/bundle-cache/bundles/${bundleName}.src`, src);""", 'bundle cache source write')
sub('const WASM_CACHE_VERSION = 2; // Bump to invalidate old byte caches', 'const WASM_CACHE_VERSION = 3; // Bump to invalidate old byte caches', 'wasm cache version')
sub('export async function getCompiledWasmModule() {', 'export async function getCompiledWasmModule(url) {', 'wasm cache get')
sub('                if (result?.bytes instanceof Uint8Array) {', '                if (result?.bytes instanceof Uint8Array && result.url === url) {', 'wasm cache url check')
sub('export async function saveWasmBytes(bytes) {', 'export async function saveWasmBytes(bytes, url) {', 'wasm cache save')
sub("            const request = store.put({ key: 'busytex', bytes, timestamp: Date.now() });", "            const request = store.put({ key: 'busytex', url, bytes, timestamp: Date.now() });", 'wasm cache put')
open(p, 'w').write(s)
p = os.path.join(OUT, 'bundles.js')
s = open(p).read()
sub('        const cached = await getBundleFromCache(bundleName);', '        const cached = await getBundleFromCache(bundleName, this.bundleBase);', 'bundle cache lookup by source')
sub('        saveBundleToCache(bundleName, decompressed);', '        saveBundleToCache(bundleName, decompressed, this.bundleBase);', 'bundle cache save by source')
open(p, 'w').write(s)
p = os.path.join(OUT, 'compiler.js')
s = open(p).read()
sub('            const cachedModule = await getCompiledWasmModule();', '            const cachedModule = await getCompiledWasmModule(this.wasmUrl);', 'wasm cache lookup by address')
sub('            saveWasmBytes(wasmBytes).catch(() => {});', '            saveWasmBytes(wasmBytes, this.wasmUrl).catch(() => {});', 'wasm cache save by address')
open(p, 'w').write(s)
print('patched siglum ->', OUT)
