# Builds Clearsnap's bundle set for the in-browser engine: Siglum's bundles (v1) plus a "biblatex" bundle (biblatex,
# logreq, csquotes, from TeX Live 2025 like the engine) so biblatex documents compile in the browser with BibTeX.
#   python3 make-bundles.py [texmf-dist]     writes site/v2/bundles: the new manifests and biblatex.data.gz,
#                                             plus links to the v1 bundle files for local testing.
# deploy-bundles.sh uploads it (the v1 data files are copied inside S3).
import gzip, json, os, shutil, sys

TEXMF = sys.argv[1] if len(sys.argv) > 1 else '/usr/local/texlive/2025/texmf-dist'
HERE = os.path.dirname(os.path.abspath(__file__))
SRC, OUT = os.path.join(HERE, 'site/v1/bundles'), os.path.join(HERE, 'site/v2/bundles')
DIRS = ['tex/latex/biblatex', 'bibtex/bst/biblatex', 'tex/latex/logreq', 'tex/latex/csquotes']

manifest = json.load(open(os.path.join(SRC, 'file-manifest.json')))
bundles = json.load(open(os.path.join(SRC, 'bundles.json')))

data, count = bytearray(), 0
for d in DIRS:
    root = os.path.join(TEXMF, d)
    assert os.path.isdir(root), f'missing {root}'
    for dirpath, _, names in sorted(os.walk(root)):
        for name in sorted(names):
            rel = os.path.relpath(os.path.join(dirpath, name), TEXMF)
            key = '/texlive/texmf-dist/' + rel
            if key in manifest:
                continue  # the engine already has it
            body = open(os.path.join(dirpath, name), 'rb').read()
            manifest[key] = {'bundle': 'biblatex', 'start': len(data), 'end': len(data) + len(body)}
            data += body
            count += 1

bundles['bundles']['biblatex'] = {'files': count, 'size': len(data), 'requires': ['utils', 'hyperref', 'tex-latex-dev']}
for pkg in ['biblatex', 'logreq', 'csquotes']:
    bundles['packages'][pkg] = 'biblatex'

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
for name in os.listdir(SRC):
    if name not in ('file-manifest.json', 'bundles.json'):
        os.symlink(os.path.join(SRC, name), os.path.join(OUT, name))
json.dump(manifest, open(os.path.join(OUT, 'file-manifest.json'), 'w'), separators=(',', ':'))
json.dump(bundles, open(os.path.join(OUT, 'bundles.json'), 'w'), separators=(',', ':'))
with open(os.path.join(OUT, 'biblatex.data.gz'), 'wb') as f:
    f.write(gzip.compress(bytes(data), compresslevel=9, mtime=0))
print(f'biblatex bundle: {count} files, {len(data)} bytes, {os.path.getsize(os.path.join(OUT, "biblatex.data.gz"))} gzipped -> {OUT}')
