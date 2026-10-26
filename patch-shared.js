// ============ Clearsnap: code the worker and the compiler both use ============
// Spliced into each by patch-worker.py and patch-siglum.py, so both reach the same answer from the same files.

// The project's other .tex files (chapters pulled in with \input), where \label and \ref usually live.
function projectTexSource(files) {
    let out = '';
    if (!files) return out;
    const entries = files instanceof Map ? files.entries() : Object.entries(files);
    for (const [path, data] of entries) {
        if (path.startsWith('/texlive') || !path.endsWith('.tex')) continue;
        try { out += '\n' + (typeof data === 'string' ? data : new TextDecoder().decode(data)); } catch (e) {}
    }
    return out;
}

// Whether a document uses the figure cache (see patch-worker-memo.js). The compiler keys and builds the preamble format
// with memoize loaded when it does.
const MEMO_DRAWINGS = /\\begin\s*\{(tikzpicture|axis|semilogxaxis|semilogyaxis|loglogaxis|polaraxis|forest|ganttchart|circuitikz|tikzcd)\}|\\tikz\b/;

// 'inject': load memoize ourselves; 'user': the document loads it; 'off': no figure cache.
function memoMode(allTex, options) {
    if (options && options.noMemoize) return 'off';
    if (/\\usepackage\s*(\[[^\]]*\])?\s*\{[^}]*\bmemoize\b/.test(allTex)) return 'user';
    if (/\\usetikzlibrary\s*\{[^}]*\bexternal\b/.test(allTex)) return 'off';
    if (/\\documentclass\s*(\[[^\]]*\])?\s*\{\s*(standalone|beamer)\s*\}/.test(allTex)) return 'off';
    return MEMO_DRAWINGS.test(allTex) ? 'inject' : 'off';
}

