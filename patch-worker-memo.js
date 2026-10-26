// ============ Clearsnap: the figure cache ============
// Drawings (TikZ, pgfplots, circuits, Gantt charts, forest trees) are cached with the memoize package. Each picture is
// keyed by its code plus a context (a fingerprint of the preamble and of the project's data files and images), drawn
// once, cut out of the PDF as its own small PDF, and reused by later compiles until its code or context changes.
// Only pictures written out in the document's own files are cached (memoize's automatic mode would also cache pictures
// that packages build from macros, whose code text stays the same while what they draw changes). Pictures that must be
// drawn fresh are skipped: tied to the page (remember picture, overlay), fill patterns (anchored to the page), links and
// references (lost in a cached picture), the date or time, and counters. The files live here between compiles; the
// compiler keeps them across visits.
const clearsnapMemo = new Map(); // file name in the memo folder -> bytes
const MEMO_DIR = '/document.memo.dir';

function memoHashBytes(h, bytes) {
    for (let i = 0; i < bytes.length; i++) h = ((h * 33) ^ bytes[i]) >>> 0;
    return h;
}

// The context every cached picture depends on: the preamble (colors, macros, packages) and the project's other files.
function memoContext(source, files) {
    const begin = source.indexOf('\\begin{document}');
    let h = quickHash(begin > 0 ? source.slice(0, begin) : source);
    const entries = files instanceof Map ? [...files.entries()] : Object.entries(files || {});
    entries.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    for (const [path, data] of entries) {
        if (path.startsWith('/texlive') || /\.tex$/.test(path)) continue;
        h = quickHash(path + ':' + h);
        h = memoHashBytes(h, typeof data === 'string' ? new TextEncoder().encode(data) : data);
    }
    return h.toString(16);
}

// Loading memoize goes right after \documentclass, or into the preamble format (memoize fixes its folder when it loads,
// so the folder is named for the document, not for the format's build). The context goes right after \begin{document},
// so the format doesn't depend on it; memoize hashes it with each picture either way.
const MEMO_LOAD =
    '\\usepackage[extract=no]{memoize}' +
    '\\mmzset{deactivate={\\tikz,tikzpicture},memo dir=document}' +
    '\\AtBeginDocument{\\ifdefined\\tikzset\\tikzset{remember picture/.append code=\\mmzAbort,overlay/.append code=\\mmzAbort}\\fi}';
const memoContextLine = ctx => '\\mmzset{context={clearsnap ' + ctx + '}}';

// Wraps each picture written out at the top level of a document's own text in a memoize environment, on the same
// lines so line numbers don't move. Not inside braces (macro definitions, \resizebox arguments) or verbatim text. The
// code is collected verbatim, so tikz-cd diagrams and TikZ matrices (& between cells) work.
const MEMO_WRAP = /^\\begin\s*\{(tikzpicture|ganttchart|circuitikz|tikzcd)\}/;
const MEMO_VERBATIM = /^\\begin\s*\{(verbatim\*?|Verbatim\*?|lstlisting|minted|comment)\}/;
const MEMO_SKIP = /remember picture|overlay|pattern|\\href|\\url\b|\\hyperlink|\\hyperref|\\(?:c|C|auto|eq|page|name|v)?ref\b|\\cite|\\today|\\year\b|\\month\b|\\day\b|\\time\b|\\the[a-zA-Z@]|\\arabic|\\[rR]oman|\\[aA]lph|\\value\s*\{|\\input\b|\\include\b/;

function memoEnvEnd(text, from, env) {
    const re = new RegExp('\\\\(begin|end)\\s*\\{' + env.replace('*', '\\*') + '\\}', 'g');
    re.lastIndex = from;
    let depth = 0, m;
    while ((m = re.exec(text))) {
        if (m[1] === 'begin') depth++;
        else if (--depth === 0) return m.index + m[0].length;
    }
    return -1;
}

function memoWrap(text, start) {
    if (start < 0) return text;
    let out = text.slice(0, start), i = start, depth = 0;
    while (i < text.length) {
        const c = text[i];
        if (c === '%') { const e = text.indexOf('\n', i); const j = e < 0 ? text.length : e; out += text.slice(i, j); i = j; continue; }
        if (c === '\\') {
            const head = text.slice(i, i + 40);
            const v = MEMO_VERBATIM.exec(head);
            const w = depth === 0 ? MEMO_WRAP.exec(head) : null;
            const env = (v || w || [])[1];
            const end = env ? memoEnvEnd(text, i, env) : -1;
            if (end > 0) {
                const body = text.slice(i, end);
                out += w && !MEMO_SKIP.test(body.replace(/(^|[^\\])%[^\n]*/g, '$1')) ? '\\begin{memoize}[verbatim]' + body + '\\end{memoize}' : body;
                i = end;
                continue;
            }
            out += text.slice(i, i + 2);
            i += 2;
            continue;
        }
        if (c === '{') depth++;
        else if (c === '}') depth = Math.max(0, depth - 1);
        out += c;
        i++;
    }
    return out;
}

function writeMemos(FS) {
    try { FS.mkdir(MEMO_DIR); } catch (e) {}
    for (const [name, data] of clearsnapMemo) {
        try { FS.writeFile(MEMO_DIR + '/' + name, data); } catch (e) {}
    }
}

// Memo files TeX wrote during a pass; returns the names that are new.
function readMemos(FS) {
    const fresh = [];
    let names = [];
    try { names = FS.readdir(MEMO_DIR); } catch (e) { return fresh; }
    for (const n of names) {
        if (!/\.(memo|pdf)$/.test(n)) continue;
        try {
            const d = FS.readFile(MEMO_DIR + '/' + n);
            const old = clearsnapMemo.get(n);
            if (!old || old.length !== d.length) { clearsnapMemo.set(n, d); fresh.push(n); }
        } catch (e) {}
    }
    return fresh;
}

// memoize ships each newly drawn picture as an extra page of the PDF. Copy those pages out as the pictures' own PDFs
// and take them out of the document.
async function extractExterns(pdfData, mmz) {
    const externs = [...mmz.matchAll(/\\mmzNewExtern\s*\{([^}]*)\}\{(\d+)\}/g)].map(m => ({ name: m[1].split('/').pop(), page: Number(m[2]) }));
    if (!externs.length) return null;
    if (!self.PDFLib) importScripts('/pdf-lib.min.js');
    const { PDFDocument } = self.PDFLib;
    const doc = await PDFDocument.load(pdfData, { updateMetadata: false });
    const made = [];
    for (const x of externs) {
        if (x.page < 1 || x.page > doc.getPageCount()) continue;
        const one = await PDFDocument.create({ updateMetadata: false });
        const [page] = await one.copyPages(doc, [x.page - 1]);
        one.addPage(page);
        clearsnapMemo.set(x.name, await one.save());
        made.push(x.name);
    }
    const removed = [...new Set(externs.map(x => x.page))].filter(p => p >= 1 && p <= doc.getPageCount()).sort((a, b) => b - a);
    for (const p of removed) doc.removePage(p - 1);
    return { pdf: await doc.save(), removed: removed.sort((a, b) => a - b), made };
}

// SyncTeX after pages were taken out: drop their records and renumber the rest.
function dropSynctexPages(synctex, removed) {
    if (!synctex || !removed.length) return synctex;
    const gone = new Set(removed);
    const shift = p => p - removed.filter(r => r < p).length;
    const out = [];
    let skip = false;
    for (const line of synctex.split('\n')) {
        const m = /^([{}])(\d+)$/.exec(line);
        if (m) {
            const p = Number(m[2]);
            if (gone.has(p)) { skip = m[1] === '{'; continue; }
            out.push(m[1] + shift(p));
            continue;
        }
        if (!skip) out.push(line);
    }
    return out.join('\n');
}

// The names this document's compile used or made (for the compiler's index of what to keep).
function memoNamesIn(mmz) {
    const keys = new Set([...mmz.matchAll(/([0-9A-F]{32}(?:-[0-9A-F]{32})?)/g)].map(m => m[1]));
    return [...clearsnapMemo.keys()].filter(n => keys.has(n.replace(/(-\d+)?\.(memo|pdf)$/, '')));
}

