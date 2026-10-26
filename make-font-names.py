# Builds bundles/font-names.json for the TeX Live 2025 mirror (make-texlive.py): every OpenType and TrueType font's
# names (family, typographic family, full name, PostScript name, file name), squeezed to lowercase letters and digits,
# mapped to the TeX Live package that has it. fontspec asks for fonts by name (\setmainfont{TeX Gyre Pagella}); when
# a compile can't find one, the engine looks the name up here and fetches that package.
#   python3 make-font-names.py [texlive-root] [out-dir]
import importlib.util, json, os, re, sys
from concurrent.futures import ProcessPoolExecutor
from fontTools.ttLib import TTCollection, TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('make_texlive', os.path.join(HERE, 'make-texlive.py'))
mt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mt)
ROOT = sys.argv[1] if len(sys.argv) > 1 else '/usr/local/texlive/2025'
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'build/tl2025')
mt.ROOT = ROOT

squeeze = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())


def names(item):
    """(package, [squeezed names]) for one package's fonts."""
    pkg, files = item
    found = set()
    for f in files:
        if not re.search(r'\.(otf|ttf|ttc|otc)$', f, re.I):
            continue
        found.add(squeeze(os.path.splitext(os.path.basename(f))[0]))
        try:
            fonts = TTCollection(os.path.join(ROOT, f), lazy=True).fonts if f.lower().endswith(('.ttc', '.otc')) \
                else [TTFont(os.path.join(ROOT, f), lazy=True, fontNumber=0)]
            for font in fonts:
                for rec in font['name'].names:
                    if rec.nameID in (1, 4, 6, 16):
                        try:
                            found.add(squeeze(rec.toUnicode()))
                        except Exception:
                            pass
        except Exception:
            pass
    return pkg, sorted(n for n in found if n)


if __name__ == '__main__':
    pkgs = [(n, f) for n, f in mt.packages() if '.' not in n and not n.startswith('00texlive')]
    index = {}
    with ProcessPoolExecutor() as pool:
        for pkg, found in pool.map(names, pkgs, chunksize=8):
            for n in found:
                index.setdefault(n, pkg)
    os.makedirs(os.path.join(OUT, 'bundles'), exist_ok=True)
    with open(os.path.join(OUT, 'bundles/font-names.json'), 'w') as fh:
        json.dump(index, fh, separators=(',', ':'), sort_keys=True)
    print(f'{len(index)} font names in {len(set(index.values()))} packages -> {OUT}/bundles/font-names.json')
