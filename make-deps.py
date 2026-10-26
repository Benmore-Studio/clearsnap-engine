# Builds package-deps.json for the in-browser engine: for every LaTeX package and class in TeX Live 2025, the
# packages and classes it loads (\RequirePackage, \usepackage, \LoadClass). The engine's pre-scan follows it to
# fetch a document's whole package tree from the mirror in parallel before compiling, instead of discovering one
# missing file per compile pass. Packages the bundles already contain are left out (they're loaded with the
# bundles). Writes site/v3/bundles: the new package-deps.json plus links to the v2 files.
#   python3 make-deps.py [texmf-dist]
import json, os, re, sys

TEXMF = sys.argv[1] if len(sys.argv) > 1 else '/usr/local/texlive/2025/texmf-dist'
HERE = os.path.dirname(os.path.abspath(__file__))
PREV, OUT = os.path.join(HERE, 'site/v2/bundles'), os.path.join(HERE, 'site/v3/bundles')

LOADS = re.compile(r'\\(?:RequirePackage|RequirePackageWithOptions|usepackage|LoadClass|LoadClassWithOptions)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}')
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')

# Prefetch only what's cheap and real: a dependency must be in TeX Live, and its archive under 2 MB (big ones are
# mostly fonts that a class loads only for some options; those still arrive on demand when actually needed).
MIRROR = os.path.join(HERE, 'build/tl2025')
index = json.load(open(os.path.join(MIRROR, 'bundles/file-to-package.json')))
def cheap(name):
    for ext in ('.sty', '.cls'):
        tl = index.get(name + ext)
        if tl:
            f = os.path.join(MIRROR, 'api/texlive', tl)
            return os.path.exists(f) and os.path.getsize(f) < 2_000_000
    return False

bundled = {os.path.basename(p).rsplit('.', 1)[0] for p in json.load(open(os.path.join(PREV, 'file-manifest.json'))) if p.endswith(('.sty', '.cls'))}
deps = {}
for dirpath, _, names in os.walk(os.path.join(TEXMF, 'tex')):
    for name in names:
        if not name.endswith(('.sty', '.cls')):
            continue
        pkg = name.rsplit('.', 1)[0]
        if pkg in bundled:
            continue
        try:
            text = open(os.path.join(dirpath, name), encoding='latin-1').read()
        except OSError:
            continue
        text = re.sub(r'(?<!\\)%[^\n]*', '', text)
        found = []
        for m in LOADS.finditer(text):
            for d in m.group(1).split(','):
                d = d.strip()
                if d and d != pkg and NAME.match(d) and d not in bundled and d not in found and cheap(d):
                    found.append(d)
        if found:
            deps.setdefault(pkg, found)

os.makedirs(OUT, exist_ok=True)
for name in os.listdir(PREV):
    dst = os.path.join(OUT, name)
    if name != 'package-deps.json' and not os.path.lexists(dst):
        os.symlink(os.path.realpath(os.path.join(PREV, name)), dst)
old = json.load(open(os.path.join(PREV, 'package-deps.json')))
merged = dict(old.get('packages', {}))
for k, v in deps.items():
    merged.setdefault(k, v)
dst = os.path.join(OUT, 'package-deps.json')
if os.path.lexists(dst):
    os.remove(dst)
json.dump({'$comment': 'Packages each LaTeX package or class loads (TeX Live 2025), for prefetching. make-deps.py', 'packages': merged}, open(dst, 'w'), separators=(',', ':'))
print(f'{len(deps)} packages with dependencies ({len(merged)} in all), {os.path.getsize(dst)} bytes -> {dst}')
