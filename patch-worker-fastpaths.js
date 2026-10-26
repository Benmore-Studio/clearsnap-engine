// ============ Clearsnap: fast paths for hot library code ============
// Some packages spend most of a compile in code TeX runs slowly, where a shortcut gives exactly the same result
// (engine/research/README.md). Each fast path (engine/fastpaths/<package>.tex, built in as CLEARSNAP_FASTPATHS) is TeX
// code that installs itself after its package loads, and only when that package's code is exactly the code it was
// written against, so another version of the package just keeps its own code. It goes right after \documentclass,
// on the same line, when the document or a project file loads the package, and into the preamble format too.
// A document can turn them off with this comment in its preamble (tests compare with and without).
const FASTPATHS_OFF = /%\s*clearsnap:\s*no fast paths/;

// A fast path applies when the document or a project file loads one of the packages or classes it names.
function fastpathsFor(text) {
    return CLEARSNAP_FASTPATHS
        .filter(f => f.when.some(n => new RegExp('\\\\(?:usepackage|RequirePackage|documentclass|LoadClass)\\s*(?:\\[[^\\]]*\\])?\\s*\\{[^}]*\\b' + n.replace('.', '\\.') + '\\b').test(text)))
        .map(f => f.tex).join('');
}

// The project's own .tex, .sty and .cls files, which can load packages too.
function fastpathText(files) {
    let out = '';
    const entries = files instanceof Map ? files.entries() : Object.entries(files || {});
    for (const [path, data] of entries) {
        if (path.startsWith('/texlive') || !/\.(tex|sty|cls)$/.test(path)) continue;
        try { out += '\n' + (typeof data === 'string' ? data : new TextDecoder().decode(data)); } catch (e) {}
    }
    return out;
}

const fastpathsAfterClass = (source, text) => {
    const fp = fastpathsFor(text);
    return fp ? source.replace(/\\documentclass\s*(?:\[[^\]]*\])?\s*\{[^}]*\}/, m => m + fp) : source;
};

