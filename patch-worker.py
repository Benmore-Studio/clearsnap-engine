# Patches Siglum's worker so every compile result carries the TeX log (upstream sends none, so the editor can't
# show errors or warnings from in-browser compiles). Fails loudly if upstream changes shape.
import os
import sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()
anchor = "    const auxFiles = compileSuccess ? collectAuxFiles(FS) : null;\n"
assert s.count(anchor) == 1, "worker.js: aux anchor not found"
s = s.replace(anchor, "    // Clearsnap: keep the TeX log for the editor's diagnostics.\n    let texLog = '';\n    try { if (FS) texLog = new TextDecoder().decode(FS.readFile('/document.log')); } catch (e) {}\n" + anchor)
needle = "            syncTexData,\n            exitCode: lastExitCode,\n"
assert s.count(needle) == 2, "worker.js: response anchors not found"
s = s.replace(needle, "            syncTexData,\n            log: texLog,\n            exitCode: lastExitCode,\n")
# Keep line numbers identical to the source the editor shows (errors and SyncTeX point at real lines):
# 1) a cached-format compile drops the preamble; leave its newlines behind instead.
a = "                    if (beginDocIdx !== -1) docSource = source.substring(beginDocIdx);\n"
assert s.count(a) == 1, "worker.js: preamble strip not found"
s = s.replace(a, "                    if (beginDocIdx !== -1) docSource = source.substring(0, beginDocIdx).replace(/[^\\n]/g, '') + source.substring(beginDocIdx);\n")
# 2) the microtype workaround goes on the same line as \\documentclass.
a = "    const workaround = '% Siglum: Disable microtype font expansion\\n\\\\PassOptionsToPackage{expansion=false}{microtype}\\n';\n"
assert s.count(a) == 1, "worker.js: microtype workaround not found"
s = s.replace(a, "    const workaround = '\\\\PassOptionsToPackage{expansion=false}{microtype}';\n")
# 3) auto-generated stubs go right after \\documentclass{...} without new lines.
a = """    const shimBlock = `
% Siglum: Auto-generated stubs for undefined commands
${stubs.join('%\\n')}%
`;"""
assert s.count(a) == 1, "worker.js: shim block not found"
s = s.replace(a, "    const shimBlock = stubs.join('');")
# 4) TeX's date: this WebAssembly build reports a fixed 2023 date, so \\today was wrong. Use the real clock.
a = "    ENV['TEXMF'] = '/texlive/texmf-dist';\n"
assert s.count(a) == 1, "worker.js: ENV anchor not found"
# TeX reads SOURCE_DATE_EPOCH as UTC, so shift it by the browser's offset: \today is then the writer's own date.
s = s.replace(a, a + "    ENV['SOURCE_DATE_EPOCH'] = String(Math.floor(Date.now() / 1000) - new Date().getTimezoneOffset() * 60);\n    ENV['FORCE_SOURCE_DATE'] = '1';\n")
# 5) BibTeX in the browser. bibtex8 is compiled into busytex.wasm but upstream never runs it, so documents with a
#    bibliography had to go to the cloud. After the first pass, when the .aux names a .bib file, run bibtex8; the
#    usual reruns then pick up the .bbl (a bibliography needs three passes in all). BibTeX's own log is appended to
#    the TeX log so the editor can show its errors.
a = "const MULTIPASS_3_REGEX = /\\\\(?:tableofcontents|listoffigures|listoftables|printindex|makeindex)\\b/;\n"
assert s.count(a) == 1, "worker.js: pass regex not found"
s = s.replace(a, "const MULTIPASS_3_REGEX = /\\\\(?:(?:tableofcontents|listoffigures|listoftables|printindex|makeindex|printbibliography|addbibresource)\\b|bibliography\\s*\\{)/;\n")
a = "    ENV['TEXINPUTS'] = "
assert s.count(a) == 1, "worker.js: TEXINPUTS anchor not found"
s = s.replace(a, "    ENV['BIBINPUTS'] = '.:/texlive/texmf-dist/bibtex/bib//';\n    ENV['BSTINPUTS'] = '.:/texlive/texmf-dist/bibtex/bst//';\n    // Unwrapped log lines, so messages (missing files, errors) aren't split mid-word at 79 characters.\n    ENV['max_print_line'] = '10000';\n    ENV['error_line'] = '254';\n    ENV['half_error_line'] = '238';\n" + a)
a = "                    // Auto-rerun loop for cross-references/TOC\n"
assert s.count(a) == 1, "worker.js: rerun anchor not found"
s = s.replace(a, """                    // Clearsnap: BibTeX, when the first pass's .aux names a .bib database.
                    try {
                        const aux = new TextDecoder().decode(FS.readFile('/document.aux'));
                        if (/\\\\bibdata\\{/.test(aux)) {
                            workerProgress('compile', 'Running BibTeX...');
                            // A .bbl restored from an earlier compile must not outlive a failed run.
                            try { FS.unlink('/document.bbl'); } catch (e) {}
                            // A style the engine doesn't ship (IEEEtran, elsarticle-num...) comes from the TeX Live
                            // mirror, into the working folder where BibTeX looks first.
                            const bst = (/\\\\bibstyle\\{([^}]+)\\}/.exec(aux) || [])[1];
                            if (bst && Module.callMainWithRedirects(['kpsewhich', bst + '.bst']).exit_code !== 0) {
                                try {
                                    const got = await requestCtanFetch(bst + '.bst', bst + '.bst');
                                    const files = got?.files instanceof Map ? got.files : new Map(Object.entries(got?.files || {}));
                                    for (const [path, content] of files) {
                                        accumulatedCtanFiles.set(path, content);
                                        if (path.endsWith('/' + bst + '.bst')) FS.writeFile('/' + bst + '.bst', content);
                                    }
                                } catch (e) { workerLog('BibTeX style fetch failed: ' + e.message); }
                            }
                            const bib = Module.callMainWithRedirects(['bibtex8', '--8bit', 'document']);
                            let blg = '';
                            try { blg = new TextDecoder().decode(FS.readFile('/document.blg')); } catch (e) {}
                            clearsnapBibLog = blg || bib.stdout || bib.stderr || '';
                            workerLog(`BibTeX exit ${bib.exit_code}`);
                        }
                    } catch (e) { workerLog('BibTeX skipped: ' + e.message); }

""" + a)
a = "async function handleCompile(request) {\n"
assert s.count(a) == 1, "worker.js: handleCompile not found"
s = s.replace(a, "let clearsnapBibLog = '';\n" + a + "    clearsnapBibLog = '';\n")
a = "    try { if (FS) texLog = new TextDecoder().decode(FS.readFile('/document.log')); } catch (e) {}\n"
assert s.count(a) == 1, "worker.js: texLog anchor not found"
s = s.replace(a, a + "    if (clearsnapBibLog) texLog += '\\n\\n%% Clearsnap: BibTeX log\\n' + clearsnapBibLog;\n")

# natbib says "There were undefined citations" / "Citation(s) may have changed"; rerun for those too.
a = "                    const rerunPattern = /Rerun to get|Label\\(s\\) may have changed|There were undefined references|Rerun LaTeX/i;\n"
assert s.count(a) == 1, "worker.js: rerun pattern not found"
s = s.replace(a, "                    const rerunPattern = /Rerun to get|Label\\(s\\) may have changed|Citation\\(s\\) may have changed|There were undefined (references|citations)|Rerun LaTeX|Please \\(re\\)run BibTeX|Please rerun LaTeX/i;\n")

# After BibTeX, the next two passes always run (to read the .bbl, then resolve the citations): the "nothing
# changed" shortcuts can be fooled by .aux files restored from an earlier compile.
a = "                        if (!logSaysRerun) break;\n"
assert s.count(a) == 1, "worker.js: logSaysRerun check not found"
s = s.replace(a, "                        if (!logSaysRerun && clearsnapBibPasses <= 0) break;\n")
a = "                        if (currentAuxHash === prevAuxHash) {\n"
assert s.count(a) == 1, "worker.js: aux hash check not found"
s = s.replace(a, "                        if (currentAuxHash === prevAuxHash && clearsnapBibPasses <= 0) {\n")
a = "                        rerunPass++;\n"
assert s.count(a) == 1, "worker.js: rerunPass++ not found"
s = s.replace(a, a + "                        clearsnapBibPasses--;\n")
s = s.replace("let clearsnapBibLog = '';\n", "let clearsnapBibLog = '';\nlet clearsnapBibPasses = 0;\n", 1)
s = s.replace("    clearsnapBibLog = '';\n", "    clearsnapBibLog = '';\n    clearsnapBibPasses = 0;\n", 1)
s = s.replace("                            workerLog(`BibTeX exit ${bib.exit_code}`);\n", "                            workerLog(`BibTeX exit ${bib.exit_code}`);\n                            clearsnapBibPasses = 2;\n", 1)

# biblatex normally uses Biber, which can't run in a browser; here it uses its BibTeX backend (bibtex8 above).
# The option goes into the existing \\usepackage line, so line numbers don't move.
a = "            docSource = injectKernelCompatShim(docSource);\n"
assert s.count(a) == 1, "worker.js: kernel shim anchor not found"
s = s.replace(a, a + """            docSource = docSource
                .replace(/(\\\\usepackage\\s*\\[)([^\\]]*)(\\]\\s*\\{\\s*biblatex\\s*\\})/, (m, open, opts, close) =>
                    open + (/\\bbackend\\s*=/.test(opts) ? opts.replace(/\\bbackend\\s*=\\s*[A-Za-z0-9]+/, 'backend=bibtex8') : (opts.trim() ? opts + ',' : '') + 'backend=bibtex8') + close)
                .replace(/\\\\usepackage\\s*\\{\\s*biblatex\\s*\\}/, '\\\\usepackage[backend=bibtex8]{biblatex}');
""")

# Two more kinds of "missing file" that the package mirror can supply: a babel language and a biblatex style.
a = "        /! LaTeX Error: File `([^']+)' not found/g,\n"
assert s.count(a) == 1, "worker.js: missing-file patterns not found"
s = s.replace(a, a + "        /! LaTeX Error: File '([^']+)' not found/g,\n        /language definition file\\s+([A-Za-z0-9_-]+\\.ldf)/g,\n        /Package biblatex Error: Style '([^']+)' not found/g,\n        /The font \"([^\"]+)\" cannot be found/g,\n")
# A biblatex style is asked for as its .bbx file (a bare name could match some unrelated .sty first).
a = "            const missingFile = match[1];\n"
assert s.count(a) == 1, "worker.js: missingFile capture not found"
s = s.replace(a, "            const missingFile = /Style '/.test(pattern.source) ? match[1] + '.bbx' : match[1];\n")

# The engine's LaTeX format leaves \\languagename undefined (a TeX Live format defines it while loading hyphenation),
# and KOMA-Script and others read it. Define it, on line 1 so line numbers don't move.
a = "            docSource = injectKernelCompatShim(docSource);\n"
assert s.count(a) == 1, "worker.js: kernel shim anchor not found (languagename)"
s = s.replace(a, a + "            docSource = '\\\\providecommand\\\\languagename{english}' + docSource;\n")

# Font names can have capitals (SkakNew-Diagram, the chess font): the missing-font patterns only took lowercase, so
# those fonts were never fetched and the compile failed with "Metric (TFM) file not found".
for a in ["        /! Font [^=]+=([a-z0-9-]+) at .* not loadable: Metric \\(TFM\\) file/g,\n",
          "        /!pdfTeX error:.*\\(file ([a-z0-9-]+)\\): Font .* not found/g,\n",
          "        /! Font ([a-z0-9-]+) at [0-9]+ not found/g,\n"]:
    assert s.count(a) == 1, "worker.js: font pattern not found: " + a.strip()
    s = s.replace(a, a.replace("[a-z0-9-]", "[A-Za-z0-9_-]"))

# Passes: upstream decided from the main file alone, and only knew \ref, \label and plain \cite. Labels usually live in
# \input files and documents use \cref, \nameref, \cite[p.~3]{x}..., so such documents got one pass and every
# reference printed as "??". Count from every project .tex file, and know every kind of reference and citation.
a = "function predictRequiredPasses(source) {\n"
assert s.count(a) == 1, "worker.js: predictRequiredPasses not found"
s = s.replace(a, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patch-shared.js')).read() + a)
a = "    const predictedPasses = predictRequiredPasses(source);\n"
assert s.count(a) == 1, "worker.js: pass prediction call not found"
s = s.replace(a, """    const clearsnapAllTex = source + projectTexSource(ctanFiles);
    const predictedPasses = predictRequiredPasses(clearsnapAllTex);
    // When nothing prints a page number from the .aux, pages moving (any edit above a label) doesn't call for a rerun.
    const clearsnapAuxNorm = PAGES_PRINTED_REGEX.test(clearsnapAllTex) ? null : auxSansPages;
""")
# A rerun only helps when the .aux changed in a way the document prints. Page numbers in \newlabel, the \@writefile
# lines for contents lists and the total page count change whenever text above them grows or shrinks; documents that
# never print them (no \pageref, contents, index, LastPage...) compared them anyway and paid a second full pass.
a = "function hashAuxFiles(auxFiles) {\n    if (!auxFiles) return 0;\n\n    let combined = 0;\n    for (const ext of AUX_EXTENSIONS) {\n        const content = auxFiles[ext];\n"
assert s.count(a) == 1, "worker.js: hashAuxFiles not found"
s = s.replace(a, r"""// Clearsnap: commands and packages that print page numbers taken from the .aux.
const PAGES_PRINTED_REGEX = /\\(?:[a-zA-Z]*pageref|[vV]ref|tableofcontents|listof[a-zA-Z]*|minitoc|printindex|makeindex)\b|LastPage|lastpage|backref|totpages|zref|\\documentclass\s*(?:\[[^\]]*\])?\s*\{beamer\}/;

// Clearsnap: .aux content without page numbers: \newlabel keeps its number and anchor but not its page, and the
// contents-list lines and the total page count are left out.
function auxSansPages(aux) {
    const group = (l, j) => { if (l[j] !== '{') return -1; let d = 0; for (let k = j; k < l.length; k++) { if (l[k] === '\\') { k++; continue; } if (l[k] === '{') d++; else if (l[k] === '}' && --d === 0) return k + 1; } return -1; };
    return aux.split('\n').filter(l => !/^\\@writefile\{|^\\gdef ?\\@abspage@last/.test(l)).map(l => {
        const m = /^\\newlabel\{[^}]*\}\{/.exec(l);
        if (!m) return l;
        const e1 = group(l, m[0].length), e2 = e1 < 0 ? -1 : group(l, e1);
        return e2 < 0 ? l : l.slice(0, e1) + '{}' + l.slice(e2);
    }).join('\n');
}

function hashAuxFiles(auxFiles, normalize) {
    if (!auxFiles) return 0;

    let combined = 0;
    for (const ext of AUX_EXTENSIONS) {
        const content = normalize && ext === '.aux' && auxFiles[ext] ? normalize(auxFiles[ext]) : auxFiles[ext];
""")
a = "                    let prevAuxHash = cachedAuxFiles ? hashAuxFiles(cachedAuxFiles) : 0;\n"
assert s.count(a) == 1, "worker.js: prevAuxHash not found"
s = s.replace(a, "                    let prevAuxHash = cachedAuxFiles ? hashAuxFiles(cachedAuxFiles, clearsnapAuxNorm) : 0;\n")
a = "                        const currentAuxHash = hashAuxFiles(currentAuxFiles);\n"
assert s.count(a) == 1, "worker.js: currentAuxHash not found"
s = s.replace(a, "                        const currentAuxHash = hashAuxFiles(currentAuxFiles, clearsnapAuxNorm);\n")
a = r"const MULTIPASS_2_REGEX = /\\(?:ref\{|pageref\{|eqref\{|autoref\{|cite[pt]?\{|citep\{|citet\{|autocite\{|textcite\{|label\{|bibliography\{|printbibliography|addbibresource)/;"
assert s.count(a) == 1, "worker.js: MULTIPASS_2_REGEX not found"
s = s.replace(a, r"const MULTIPASS_2_REGEX = /\\(?:[a-zA-Z]*ref\*?\{|[a-zA-Z]*cite[a-zA-Z]*\*?[\[{]|label\{|bibliography\{|printbibliography|addbibresource)/;")

# An engine crash (a WebAssembly trap such as "memory access out of bounds") was only logged; the response looked like
# an ordinary LaTeX failure. Report it as the error so the compiler can tell the two apart (and retry without the
# cached format, see patch-siglum.py).
a = "    let lastExitCode = -1;\n    let Module = null;\n"
assert s.count(a) == 1, "worker.js: lastExitCode anchor not found"
s = s.replace(a, a + "    let clearsnapCrash = '';\n")
a = "        } catch (e) {\n            workerLog(`Error: ${e.message}`);\n            break;\n        }\n"
assert s.count(a) == 1, "worker.js: compile catch not found"
s = s.replace(a, "        } catch (e) {\n            workerLog(`Error: ${e.message}`);\n            if (e && e.stack) workerLog('Engine crash stack: ' + String(e.stack).split('\\n').slice(0, 25).join(' <- '));\n            clearsnapCrash = String(e.message || e);\n            break;\n        }\n")
a = "            log: texLog,\n            exitCode: lastExitCode,\n"
assert s.count(a) == 2, "worker.js: response log anchors not found"
s = s.replace(a, "            log: texLog,\n            error: clearsnapCrash || undefined,\n            exitCode: lastExitCode,\n")

# Progress for the editor's loader: a package or font bundle being fetched mid-compile.
for a in ["                            workerLog(`Missing: ${missingFile}, loading bundle ${bundleName}...`);\n",
          "                            workerLog(`Missing: ${missingFile}, fetching ${pkgName}${yearLabel} from CTAN...`);\n"]:
    assert s.count(a) == 1, "worker.js: fetch log not found: " + a.strip()
    s = s.replace(a, a + "                            workerProgress('fetch', " + ("bundleName" if "bundle" in a else "pkgName") + ");\n")

# The figure cache (patch-worker-memo.js): memoize, the pictures cut out of the PDF, and the files kept between compiles.
memo_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patch-worker-memo.js')).read()
def once(a, b, what):
    global s
    assert s.count(a) == 1, "worker.js: " + what + " not found"
    s = s.replace(a, b)
once("async function handleCompile(request) {\n", memo_js + "async function handleCompile(request) {\n", 'handleCompile')
once("    const { id, source, engine, options, bundleData, bundleNames, ctanFiles, cachedFormat, cachedAuxFiles, deferredBundleNames } = request;\n",
     "    let { id, source, engine, options, bundleData, bundleNames, ctanFiles, cachedFormat, cachedAuxFiles, deferredBundleNames, cachedMemoFiles } = request;\n", 'compile request fields')
once("    const clearsnapAuxNorm = PAGES_PRINTED_REGEX.test(clearsnapAllTex) ? null : auxSansPages;\n",
     "    const clearsnapAuxNorm = PAGES_PRINTED_REGEX.test(clearsnapAllTex) ? null : auxSansPages;\n"
     "    // Clearsnap: the figure cache. A document that uses it gets a preamble format with memoize loaded (keyed apart by the\n"
     "    // compiler, which says whether the format it sent has memoize); a format that doesn't match isn't used.\n"
     "    if (cachedMemoFiles) for (const [n, d] of Object.entries(cachedMemoFiles)) if (!clearsnapMemo.has(n)) clearsnapMemo.set(n, d);\n"
     "    let clearsnapMemoMode = memoMode(clearsnapAllTex, options);\n"
     "    let clearsnapMemoFailed = false;\n"
     "    const clearsnapMemoFresh = new Set();\n"
     "    const clearsnapMemoCtx = clearsnapMemoMode === 'inject' ? memoContext(source, ctanFiles) : '';\n"
     "    if (cachedFormat && (clearsnapMemoMode === 'user' || (clearsnapMemoMode === 'inject') !== !!(options && options.memoFormat))) { workerLog('The cached format does not match the figure cache; compiling without it'); cachedFormat = null; }\n"
     "    // The project's other .tex files get their pictures wrapped too (kept unwrapped in case the cache is turned off).\n"
     "    const clearsnapMemoOriginals = new Map();\n"
     "    if (clearsnapMemoMode === 'inject') for (const [p, d] of accumulatedCtanFiles) {\n"
     "        if (p.startsWith('/texlive') || !p.endsWith('.tex')) continue;\n"
     "        const t = typeof d === 'string' ? d : new TextDecoder().decode(d);\n"
     "        const w = memoWrap(t, 0);\n"
     "        if (w !== t) { clearsnapMemoOriginals.set(p, d); accumulatedCtanFiles.set(p, new TextEncoder().encode(w)); }\n"
     "    }\n",
     'aux norm anchor')
once("            FS.writeFile('/document.tex', docSource);\n\n            // Run compilation\n",
     "            if (clearsnapMemoMode === 'inject') { if (!cachedFormat) docSource = docSource.replace(/\\\\documentclass\\s*(?:\\[[^\\]]*\\])?\\s*\\{[^}]*\\}/, m => m + MEMO_LOAD); docSource = docSource.replace('\\\\begin{document}', m => m + memoContextLine(clearsnapMemoCtx)); docSource = memoWrap(docSource, docSource.indexOf('\\\\begin{document}')); }\n"
     "            FS.writeFile('/document.tex', docSource);\n\n            // Run compilation\n", 'first document write')
once("                if (restored > 0) workerLog(`Restored ${restored} aux files`);\n            }\n",
     "                if (restored > 0) workerLog(`Restored ${restored} aux files`);\n            }\n            if (clearsnapMemoMode !== 'off') writeMemos(FS);\n", 'aux restore')
once("                        restoreAuxFiles(FS, rerunAuxFiles);\n",
     "                        restoreAuxFiles(FS, rerunAuxFiles);\n                        if (clearsnapMemoMode !== 'off') writeMemos(FS);\n", 'rerun aux restore')
once("                    compileSuccess = true;\n",
     "                    compileSuccess = true;\n                    if (clearsnapMemoMode !== 'off') for (const n of readMemos(FS)) clearsnapMemoFresh.add(n);\n", 'first success')
once("                            workerLog(`Rerun ${rerunPass} successful`);\n",
     "                            workerLog(`Rerun ${rerunPass} successful`);\n                            if (clearsnapMemoMode !== 'off') for (const n of readMemos(FS)) clearsnapMemoFresh.add(n);\n", 'rerun success')
once("            // No more retries possible\n",
     "            // Clearsnap: an error from the figure cache's own packages: compile once more without it.\n"
     "            if (!compileSuccess && clearsnapMemoMode === 'inject') {\n"
     "                let first = '';\n"
     "                try { first = FS.readFile('/document.log', { encoding: 'utf8' }).split('\\n').find(l => l.startsWith('! ')) || ''; } catch (e) {}\n"
     "                if (/collargs|advice|memoize|\\\\mmz/i.test(first)) {\n"
     "                    workerLog('The figure cache caused an error; compiling without it');\n"
     "                    clearsnapMemoMode = 'off'; clearsnapMemoFailed = true; cachedFormat = null; retryCount++;\n"
     "                    for (const [p, d] of clearsnapMemoOriginals) accumulatedCtanFiles.set(p, d);\n"
     "                    continue;\n"
     "                }\n"
     "            }\n"
     "            // No more retries possible\n", 'retry tail')
once("    // Clearsnap: keep the TeX log for the editor's diagnostics.\n",
     "    // Clearsnap: cut the newly drawn pictures out of the PDF; they become the figure cache.\n"
     "    let clearsnapMemoNames = null;\n"
     "    if (compileSuccess && clearsnapMemoMode !== 'off' && pdfData) {\n"
     "        try {\n"
     "            let mmz = '';\n"
     "            try { mmz = FS.readFile('/document.mmz', { encoding: 'utf8' }); } catch (e) {}\n"
     "            if (mmz) {\n"
     "                const x = await extractExterns(pdfData, mmz);\n"
     "                if (x) {\n"
     "                    pdfData = x.pdf.slice();\n"
     "                    syncTexData = dropSynctexPages(syncTexData, x.removed);\n"
     "                    for (const n of x.made) clearsnapMemoFresh.add(n);\n"
     "                    workerLog(`Figure cache: ${x.made.length} new picture(s) saved`);\n"
     "                }\n"
     "                clearsnapMemoNames = memoNamesIn(mmz);\n"
     "            }\n"
     "        } catch (e) { clearsnapMemoFailed = true; workerLog('Figure cache: could not save the pictures: ' + e.message); }\n"
     "    }\n\n"
     "    // Clearsnap: keep the TeX log for the editor's diagnostics.\n", 'log anchor')
a = "            log: texLog,\n            error: clearsnapCrash || undefined,\n"
assert s.count(a) == 2, "worker.js: response anchors (memo) not found"
s = s.replace(a, a + "            memoFiles: clearsnapMemoFresh.size ? Object.fromEntries([...clearsnapMemoFresh].map(n => [n, clearsnapMemo.get(n)]).filter(e => e[1])) : undefined,\n"
                     "            memoNames: clearsnapMemoNames || undefined,\n"
                     "            memoize: clearsnapMemoFailed ? 'failed' : clearsnapMemoMode,\n")

# Formats and PDF objects (patch-worker-format.js): PGF's shadings and fadings are declared at \begin{document} while a
# format is built; no format for preambles that make PDF objects in other ways; a format that reports dangling objects
# is thrown away.
fmt_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patch-worker-format.js')).read()
once("async function handleCompile(request) {\n", fmt_js + "async function handleCompile(request) {\n", 'handleCompile (format helpers)')
once("            const shimmedPreamble = injectKernelCompatShim(preambleContent);\n",
     "            const clearsnapFmtSource = formatSource(request.memoize ? preambleContent.replace(/\\\\documentclass\\s*(?:\\[[^\\]]*\\])?\\s*\\{[^}]*\\}/, m => m + MEMO_LOAD) : preambleContent);\n"
     "            if (clearsnapFmtSource === null) {\n"
     "                workerLog('No format for this preamble: it makes PDF objects');\n"
     "                self.postMessage({ type: 'format-generate-response', id, success: false, error: 'preamble makes PDF objects' });\n"
     "                return;\n"
     "            }\n"
     "            const shimmedPreamble = injectKernelCompatShim(clearsnapFmtSource);\n", 'format source')
once("            if (result.exit_code === 0) {\n                const formatData = FS.readFile('/myformat.fmt');\n",
     "            if (result.exit_code === 0) {\n"
     "                let clearsnapFmtLog = '';\n"
     "                try { clearsnapFmtLog = new TextDecoder().decode(FS.readFile('/myformat.log')); } catch (e) {}\n"
     "                if (/dangling objects discarded/.test(clearsnapFmtLog + ' ' + (result.stdout || '') + ' ' + (result.stderr || ''))) {\n"
     "                    workerLog('Format discarded: it would hold PDF objects');\n"
     "                    self.postMessage({ type: 'format-generate-response', id, success: false, error: 'format would hold PDF objects' });\n"
     "                    return;\n"
     "                }\n"
     "                const formatData = FS.readFile('/myformat.fmt');\n", 'format success')

# Font expansion (microtype) stays on, as in pdfLaTeX everywhere else: Siglum turned it off for every compile without a
# cached format, so a document's lines broke differently from native pdfLaTeX, and changed once its format was cached.
# It needs outline fonts; a document set in bitmap fonts compiles again without it (and without its format, which has
# microtype loaded already).
once("    let clearsnapMemoFailed = false;\n", "    let clearsnapMemoFailed = false;\n    let clearsnapNoExpansion = false;\n", 'expansion flag')
once("            if (engine === 'pdflatex' && !cachedFormat) {\n                docSource = injectMicrotypeWorkaround(docSource);\n",
     "            if (engine === 'pdflatex' && clearsnapNoExpansion) {\n                docSource = injectMicrotypeWorkaround(docSource);\n", 'expansion workaround only after the error')
once("            // No more retries possible\n",
     "            if (!compileSuccess && !clearsnapNoExpansion && engine === 'pdflatex') {\n"
     "                let clearsnapLog = '';\n"
     "                try { clearsnapLog = FS.readFile('/document.log', { encoding: 'utf8' }); } catch (e) {}\n"
     "                if (/pdfTeX error \\(font expansion\\)/.test(clearsnapLog)) {\n"
     "                    workerLog('Font expansion needs outline fonts; compiling without it');\n"
     "                    clearsnapNoExpansion = true; cachedFormat = null; retryCount++;\n"
     "                    continue;\n"
     "                }\n"
     "            }\n"
     "            // No more retries possible\n", 'expansion retry')

# TikZ libraries from packages outside PGF (shadows.blur, ext.paths.ortho...) have dots in their file names; the missing
# file pattern takes them, so the package is fetched.
once("        /I looked for files named ([a-z0-9_-]+\\.code\\.tex)/gi,\n",
     "        /I looked for files named ([a-z0-9_.-]+\\.code\\.tex)/gi,\n", 'library file names with dots')

# LuaLaTeX (patch-worker-lua.js): LuaHBTeX with a LaTeX format built in the browser on first use and kept.
lua_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patch-worker-lua.js')).read()
once("async function handleCompile(request) {\n", lua_js + "async function handleCompile(request) {\n", 'handleCompile (LuaLaTeX helpers)')
once("    let { id, source, engine, options, bundleData, bundleNames, ctanFiles, cachedFormat, cachedAuxFiles, deferredBundleNames, cachedMemoFiles } = request;\n",
     "    let { id, source, engine, options, bundleData, bundleNames, ctanFiles, cachedFormat, cachedAuxFiles, deferredBundleNames, cachedMemoFiles } = request;\n"
     "    if (request.cachedLuaFormat && !clearsnapLuaFmt) clearsnapLuaFmt = request.cachedLuaFormat;\n"
     "    for (const [rel, data] of Object.entries(request.cachedLuaCache || {})) if (!clearsnapLuaCache.has(rel)) clearsnapLuaCache.set(rel, data);\n"
     "    clearsnapLuaCacheFresh.clear();\n"
     "    clearsnapLuaFmtNew = false;\n    await luaFormatInflated();\n", 'LuaLaTeX cached format')
once("""            } else {
                result = Module.callMainWithRedirects([
                    'xelatex', '--no-shell-escape', '--interaction=nonstopmode',
""", """            } else if (engine === 'lualatex' && !clearsnapLuaFmt) {
                // LuaTeX can't run twice in one engine instance: build the format here, compile in a fresh one.
                result = luaFormat(Module, FS);
                if (result.exit_code === 0) { retryCount++; continue; }
            } else if (engine === 'lualatex') {
                luaFormat(Module, FS);
                result = Module.callMainWithRedirects(luaArgs());
                readLuaCache(FS);
            } else {
                result = Module.callMainWithRedirects([
                    'xelatex', '--no-shell-escape', '--interaction=nonstopmode',
""", 'LuaLaTeX first run')
once("""                        } else {
                            // XeLaTeX: two-step process (xelatex -> xdvipdfmx)
""", """                        } else if (engine === 'lualatex') {
                            luaFormat(Module, FS);
                            rerunResult = Module.callMainWithRedirects(luaArgs());
                            readLuaCache(FS);
                        } else {
                            // XeLaTeX: two-step process (xelatex -> xdvipdfmx)
""", 'LuaLaTeX rerun')
assert s.count("            exitCode: lastExitCode,\n") == 2, 'response anchors'
s = s.replace("            exitCode: lastExitCode,\n", "            exitCode: lastExitCode,\n            luaFormat: clearsnapLuaFmtNew ? clearsnapLuaFmt : null,\n            luaCache: clearsnapLuaCacheFresh.size ? Object.fromEntries([...clearsnapLuaCacheFresh].map(r => [r, clearsnapLuaCache.get(r)])) : undefined,\n")

# LuaTeX words a missing font's metrics differently: "! Font \tenln=line10 not loadable: metric data not found or bad."
once("        /! Font ([A-Za-z0-9_-]+) at [0-9]+ not found/g,\n",
     "        /! Font ([A-Za-z0-9_-]+) at [0-9]+ not found/g,\n        /! Font [^=]+=([A-Za-z0-9_-]+) not loadable: metric data not found/g,\n", 'LuaTeX missing font pattern')

# Snapshots and resume (patch-worker-snapshot.js, busytex-build/patch-snapshot.py): pdfLaTeX and XeLaTeX runs take
# snapshots of TeX at \begin{document} and after pages, and a compile resumes from the latest one its input allows. A
# resumed run that fails is done again in full.
snap_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patch-worker-snapshot.js')).read()
once("async function handleCompile(request) {\n", snap_js + "async function handleCompile(request) {\n", 'handleCompile (snapshot helpers)')
once("    const elapsed = (performance.now() - startTime).toFixed(0);\n    workerLog(`WASM ready in ${elapsed}ms`);\n",
     "    // Clearsnap: like callMainWithRedirects, for a resumed run (an exported function instead of main).\n"
     "    Module.callWithRedirects = function(fn) {\n"
     "        outputCapture.stdout.length = 0;\n"
     "        outputCapture.stderr.length = 0;\n"
     "        let exit_code = 0;\n"
     "        try { fn(); } catch (e) { if (e && e.name === 'ExitStatus') exit_code = e.status; else throw e; }\n"
     "        Module._flush_streams();\n"
     "        return { exit_code, stdout: outputCapture.stdout.join('\\n'), stderr: outputCapture.stderr.join('\\n') };\n"
     "    };\n\n"
     "    const elapsed = (performance.now() - startTime).toFixed(0);\n    workerLog(`WASM ready in ${elapsed}ms`);\n", 'callWithRedirects')
once("    let clearsnapNoExpansion = false;\n", "    let clearsnapNoExpansion = false;\n    let clearsnapNoResume = false;\n", 'resume flag')
once("""            if (engine === 'pdflatex') {
                result = Module.callMainWithRedirects([
                    'pdflatex', '--no-shell-escape', '--interaction=nonstopmode',
                    '--halt-on-error', '--synctex=-1', '--fmt=' + fmtPath, '/document.tex'
                ]);
""", """            if (engine === 'pdflatex') {
                result = snapRun(Module, engine, docSource, [
                    'pdflatex', '--no-shell-escape', '--interaction=nonstopmode',
                    '--halt-on-error', '--synctex=-1', '--fmt=' + fmtPath, '/document.tex'
                ], !clearsnapNoResume, clearsnapAuxNorm, options.clearsnapKey);
""", 'pdflatex first run')
once("""                result = Module.callMainWithRedirects([
                    'xelatex', '--no-shell-escape', '--interaction=nonstopmode',
                    '--halt-on-error', '--synctex=-1', '--no-pdf',
                    '--fmt=/texlive/texmf-dist/texmf-var/web2c/xetex/xelatex.fmt',
                    '/document.tex'
                ]);
                if (result.exit_code === 0) {
                    result = Module.callMainWithRedirects([
                        'xdvipdfmx', '-o', '/document.pdf', '/document.xdv'
                    ]);
                }
""", """                result = snapRun(Module, engine, docSource, [
                    'xelatex', '--no-shell-escape', '--interaction=nonstopmode',
                    '--halt-on-error', '--synctex=-1', '--no-pdf',
                    '--fmt=/texlive/texmf-dist/texmf-var/web2c/xetex/xelatex.fmt',
                    '/document.tex'
                ], !clearsnapNoResume, clearsnapAuxNorm, options.clearsnapKey);
                if (result.exit_code === 0) {
                    const resumed = result.clearsnapResumed;
                    result = Module.callMainWithRedirects([
                        'xdvipdfmx', '-o', '/document.pdf', '/document.xdv'
                    ]);
                    result.clearsnapResumed = resumed;
                }
""", 'xelatex first run')
once("            lastExitCode = result.exit_code;\n",
     "            if (result.clearsnapResumed !== undefined && result.exit_code !== 0) {\n"
     "                workerLog('The resumed run failed; compiling in full');\n"
     "                clearsnapSnaps = [];\n"
     "                clearsnapNoResume = true;\n"
     "                retryCount++;\n"
     "                continue;\n"
     "            }\n"
     "            lastExitCode = result.exit_code;\n", 'resume failure')
once("""                        if (engine === 'pdflatex') {
                            rerunResult = Module.callMainWithRedirects([
                                'pdflatex', '--no-shell-escape', '--interaction=nonstopmode',
                                '--halt-on-error', '--synctex=-1', '--fmt=' + fmtPath, '/document.tex'
                            ]);
""", """                        if (engine === 'pdflatex') {
                            rerunResult = snapRun(Module, engine, docSource, [
                                'pdflatex', '--no-shell-escape', '--interaction=nonstopmode',
                                '--halt-on-error', '--synctex=-1', '--fmt=' + fmtPath, '/document.tex'
                            ], false, clearsnapAuxNorm, options.clearsnapKey);
""", 'pdflatex rerun')
once("""                            rerunResult = Module.callMainWithRedirects([
                                'xelatex', '--no-shell-escape', '--interaction=nonstopmode',
                                '--halt-on-error', '--synctex=-1', '--no-pdf',
                                '--fmt=' + fmtPath, '/document.tex'
                            ]);
""", """                            rerunResult = snapRun(Module, engine, docSource, [
                                'xelatex', '--no-shell-escape', '--interaction=nonstopmode',
                                '--halt-on-error', '--synctex=-1', '--no-pdf',
                                '--fmt=' + fmtPath, '/document.tex'
                            ], false, clearsnapAuxNorm, options.clearsnapKey);
""", 'xelatex rerun')
once("    // Clearsnap: cut the newly drawn pictures out of the PDF; they become the figure cache.\n",
     "    // Clearsnap: the last run's snapshots are the next compile's to resume from.\n"
     "    clearsnapSnaps = compileSuccess ? clearsnapRunSnaps : [];\n"
     "    clearsnapRunSnaps = [];\n"
     "    // Clearsnap: cut the newly drawn pictures out of the PDF; they become the figure cache.\n", 'keep snapshots')

# LuaLaTeX runs take snapshots and resume too (busytex-build/patch-snapshot.py patches LuaTeX's main loop).
once("const SNAP_ENGINE = { pdflatex: 'pdftex', xelatex: 'xetex' };", "const SNAP_ENGINE = { pdflatex: 'pdftex', xelatex: 'xetex', lualatex: 'luatex' };", 'LuaLaTeX snapshots')
once("""                luaFormat(Module, FS);
                result = Module.callMainWithRedirects(luaArgs());
                readLuaCache(FS);
""", """                luaFormat(Module, FS);
                result = snapRun(Module, engine, docSource, luaArgs(), !clearsnapNoResume, clearsnapAuxNorm, options.clearsnapKey);
                readLuaCache(FS);
""", 'LuaLaTeX first run snapshots')
once("""                            luaFormat(Module, FS);
                            rerunResult = Module.callMainWithRedirects(luaArgs());
                            readLuaCache(FS);
""", """                            luaFormat(Module, FS);
                            rerunResult = snapRun(Module, engine, docSource, luaArgs(), false, clearsnapAuxNorm, options.clearsnapKey);
                            readLuaCache(FS);
""", 'LuaLaTeX rerun snapshots')

# Snapshots kept across visits (patch-worker-snapshot.js): read at the start of a compile, saved after a successful one.
once("    clearsnapLuaFmtNew = false;\n", "    clearsnapLuaFmtNew = false;\n    await snapFromStore(options && options.clearsnapKey);\n", 'snapshots from store')
once("    clearsnapSnaps = compileSuccess ? clearsnapRunSnaps : [];\n",
     "    clearsnapSnaps = compileSuccess ? clearsnapRunSnaps : [];\n    if (compileSuccess) snapStoreLater(options && options.clearsnapKey, clearsnapSnaps);\n", 'snapshots to store')

# A faster file system for TeX's file searches (patch-worker-fs.js): lookups and listings under /texlive remembered
# while TeX runs, and a quicker free file descriptor.
fs_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patch-worker-fs.js')).read()
once("async function handleCompile(request) {\n", fs_js + "async function handleCompile(request) {\n", 'handleCompile (fast FS)')
once("    const Module = await busytex(moduleConfig);\n    const FS = Module.FS;\n",
     "    const Module = await busytex(moduleConfig);\n    const FS = Module.FS;\n    clearsnapFastFS(Module);\n", 'fast FS install')
once("        if (args.length > 0) Module.setPrefix(args[0]);\n        const exit_code = Module.callMain(args);\n",
     "        if (args.length > 0) Module.setPrefix(args[0]);\n        Module.clearsnapFastFS(true);\n        let exit_code;\n        try { exit_code = Module.callMain(args); } finally { Module.clearsnapFastFS(false); }\n", 'fast FS during runs')
once("        try { fn(); } catch (e) { if (e && e.name === 'ExitStatus') exit_code = e.status; else throw e; }\n",
     "        Module.clearsnapFastFS(true);\n        try { fn(); } catch (e) { if (e && e.name === 'ExitStatus') exit_code = e.status; else throw e; } finally { Module.clearsnapFastFS(false); }\n", 'fast FS during resumed runs')

# Lazy fonts (patch-worker-lazyfonts.js, make-bundles-v5.py): a deferred bundle's file is fetched on its own when
# TeX opens it. The marker keeps its path; when the fetch fails, the old way (fail, fetch the bundle, rerun) remains.
lazy_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patch-worker-lazyfonts.js')).read()
once("async function handleCompile(request) {\n", lazy_js + "async function handleCompile(request) {\n", 'handleCompile (lazy fonts)')
once("            node.contents = this._createDeferredMarker(bundleName, start, end);\n",
     "            node.contents = Object.assign(this._createDeferredMarker(bundleName, start, end), { path });\n", 'deferred marker path')
once("        // Track individual file request for Range-based fetching (avoid duplicates)\n",
     "        const own = marker.path ? clearsnapFetchFile(marker.path, marker.end - marker.start) : null;\n"
     "        if (own) {\n            this.storeFetchedFile(marker.bundleName, marker.start, marker.end, own);\n            return own;\n        }\n\n"
     "        // Track individual file request for Range-based fetching (avoid duplicates)\n", 'deferred file fetch')
# Building a preamble's format sees the deferred bundles too (upstream mounted only the loaded ones: with the font
# bundles deferred, a preamble that loads a font failed to dump on every retry, and the next compile waited for it).
once("            if (accumulatedCtanFiles.size > 0) {\n                vfs.mountCtanFiles(accumulatedCtanFiles);\n            }\n\n            vfs.finalize();\n",
     "            if (!Module._lazyPatchApplied) { vfs.patchForLazyLoading(); Module._lazyPatchApplied = true; }\n"
     "            for (const bundleName of (bundleDeps?.deferred || [])) {\n"
     "                if (!bundleDataMap.has(bundleName)) vfs.mountDeferredBundle(bundleName, fileManifest, null);\n            }\n\n"
     "            if (accumulatedCtanFiles.size > 0) {\n                vfs.mountCtanFiles(accumulatedCtanFiles);\n            }\n\n            vfs.finalize();\n", 'deferred bundles in formats')
# A format that fails for any reason but a missing file fails the same way again: say so at once. Upstream retried
# the identical run up to maxRetries times (40 here, about 17 s for a KOMA-Script preamble), and the next compile
# waited for it. The compiler then marks the preamble and doesn't try it again.
once("            throw new Error(`Format generation failed with exit code ${result.exit_code}`);\n",
     "            workerLog(`Format generation failed with exit code ${result.exit_code}`);\n"
     "            self.postMessage({ type: 'format-generate-response', id, success: false, error: `exit code ${result.exit_code}` });\n"
     "            return;\n", 'format failure without retries')

# Fast paths for hot library code (patch-worker-fastpaths.js, fastpaths/<package>.tex): built in as one line each.
fp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fastpaths')
fastpaths = []
for name in sorted(os.listdir(fp_dir)):
    if name.endswith('.tex'):
        lines = open(os.path.join(fp_dir, name)).read().split('\n')
        when = [w.strip() for w in lines[0][len('% when:'):].split(',')] if lines[0].startswith('% when:') else [name[:-4]]
        # One line per fast path, read as TeX reads the file: a comment and the line end go, and a line end without a
        # comment becomes one space (leading spaces are skipped either way). Fast paths have no blank lines.
        import re as _re
        tex = ''
        for l in lines:
            body = _re.sub(r'(?<!\\)%.*$', '', l).strip()
            if not body:
                continue
            tex += body + ('' if _re.search(r'(?<!\\)%', l) else ' ')
        fastpaths.append({'when': when, 'tex': tex})
import json
fp_js = 'const CLEARSNAP_FASTPATHS = ' + json.dumps(fastpaths) + ';\n' + open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patch-worker-fastpaths.js')).read()
once("async function handleCompile(request) {\n", fp_js + "async function handleCompile(request) {\n", 'handleCompile (fast paths)')
once("            FS.writeFile('/document.tex', docSource);\n\n            // Run compilation\n",
     "            if (!cachedFormat && !FASTPATHS_OFF.test(source)) docSource = fastpathsAfterClass(docSource, source + fastpathText(ctanFiles));\n"
     "            FS.writeFile('/document.tex', docSource);\n\n            // Run compilation\n", 'fast paths in the document')
once("            const clearsnapFmtSource = formatSource(request.memoize ? preambleContent.replace(",
     "            const clearsnapFmtSource = formatSource(fastpathsAfterClass(request.memoize ? preambleContent.replace(", 'fast paths in formats (1)')
once(" m => m + MEMO_LOAD) : preambleContent);\n",
     " m => m + MEMO_LOAD) : preambleContent, FASTPATHS_OFF.test(preambleContent) ? '' : preambleContent + fastpathText(ctanFiles)));\n", 'fast paths in formats (2)')

open(dst, "w").write(s)
print("patched worker ->", dst)
