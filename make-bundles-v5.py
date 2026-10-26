# Bundle set v5 for the in-browser engine: what a first visit and a first use of a package download.
#
# 1) No documentation. The package bundles carried TeX Live's doc/ and source/ trees (manuals as PDF, .dtx sources),
#    which TeX never reads: 100 MB of the 330, among them 34 MB of pgf-tikz (32 MB to download for any TikZ picture)
#    and nearly all of xref, boxes (tcolorbox), typography (fontspec, microtype) and utils. They are left out, so
#    those bundles are rebuilt with new offsets (storage.js's bundle cache version goes up with them).
# 2) Lazy fonts. The font bundles (Computer Modern and AMS Type 1, Latin Modern, cm-super...) were downloaded whole:
#    13 MB on every first visit, and all 59.5 MB of cm-super for the one font a bullet list needs. Each of their files
#    is now published on its own at /v5/files/<path>; the worker fetches a file when TeX opens it
#    (patch-worker-lazyfonts.js), and the files the editor's templates use are fetched in parallel while the engine
#    loads (src/prefetch.json).
#   python3 make-bundles-v5.py      writes site/v5/bundles, site/v5/files and src/prefetch.json
# deploy-bundles-v5.sh uploads it. Needs a local TeX Live 2025 (pdflatex) to see which files the templates open.
import gzip, json, os, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
V3, V5 = os.path.join(HERE, 'site/v3/bundles'), os.path.join(HERE, 'site/v5')
TL = '/usr/local/texlive/2025/'
# Fetched a file at a time. LuaLaTeX still loads its fonts whole (luaotfload reads every font to build its name list).
LAZY = ['fonts-cm', 'fonts-lm-type1', 'fonts-misc', 'fonts-lm-tfm', 'fonts-lm-otf', 'cm-super', 'extra-cjk', 'extra-misc']
# Bundles that are only sources (a package maps to them; their files stay).
KEEP_SOURCES = ['source-latex', 'source-misc']
doc = lambda path: '/texmf-dist/doc/' in path or '/texmf-dist/source/' in path

bundles = json.load(open(os.path.join(V3, 'bundles.json')))
manifest = json.load(open(os.path.join(V3, 'file-manifest.json')))
for engine, deps in bundles['engines'].items():
    if engine != 'lualatex':
        deps['required'] = [b for b in deps['required'] if b not in LAZY]
bundles['deferred'] = sorted(set(bundles['deferred']) | set(LAZY))
for info in bundles['bundles'].values():
    if info.get('requires'):
        info['requires'] = [b for b in info['requires'] if b not in LAZY]
bundles['packages'] = {p: b for p, b in bundles['packages'].items() if b not in LAZY}

shutil.rmtree(V5, ignore_errors=True)
os.makedirs(os.path.join(V5, 'bundles'))
data = lambda name: gzip.open(os.path.join(V3, name + '.data.gz')).read()

# 1) Bundles without their documentation, rebuilt with new offsets; the others are v3's files (linked here).
files_of = {}
for path, info in manifest.items():
    files_of.setdefault(info['bundle'], []).append(path)
new_manifest, before, after = {}, 0, 0
for name in sorted(files_of):
    paths = sorted(files_of[name], key=lambda p: manifest[p]['start'])
    gz = os.path.join(V3, name + '.data.gz')
    if name in KEEP_SOURCES or not any(doc(p) for p in paths):
        for p in paths:
            new_manifest[p] = manifest[p]
        os.symlink(os.path.relpath(os.path.realpath(gz), os.path.join(V5, 'bundles')), os.path.join(V5, 'bundles', name + '.data.gz'))
        continue
    old, out = data(name), bytearray()
    for p in paths:
        if doc(p):
            continue
        info = manifest[p]
        new_manifest[p] = {'bundle': name, 'start': len(out), 'end': len(out) + info['end'] - info['start']}
        out += old[info['start']:info['end']]
    with gzip.GzipFile(os.path.join(V5, 'bundles', name + '.data.gz'), 'wb', compresslevel=9, mtime=0) as f:
        f.write(out)
    bundles['bundles'][name]['files'] = sum(1 for p in paths if not doc(p))
    bundles['bundles'][name]['size'] = len(out)
    b, a = os.path.getsize(os.path.realpath(gz)), os.path.getsize(os.path.join(V5, 'bundles', name + '.data.gz'))
    before, after = before + b, after + a
    print(f'  {name:16} {b / 1e6:6.2f} MB -> {a / 1e6:6.2f} MB')
print(f'bundles without documentation: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB to download')
json.dump(new_manifest, open(os.path.join(V5, 'bundles/file-manifest.json'), 'w'), separators=(',', ':'))
json.dump(bundles, open(os.path.join(V5, 'bundles/bundles.json'), 'w'), separators=(',', ':'))
for name in os.listdir(V3):
    if not os.path.lexists(os.path.join(V5, 'bundles', name)):
        os.symlink(os.path.relpath(os.path.realpath(os.path.join(V3, name)), os.path.join(V5, 'bundles')), os.path.join(V5, 'bundles', name))

# 2) The lazy bundles' files, one per path, cut from the bundle data exactly as the worker would mount it.
count = size = 0
for name in LAZY:
    old = data(name)
    for path in files_of[name]:
        info = manifest[path]
        out = os.path.join(V5, 'files', path.lstrip('/'))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, 'wb').write(old[info['start']:info['end']])
        count += 1
        size += info['end'] - info['start']
print(f'{count} font files, {size / 1e6:.1f} MB, in site/v5/files')

# The templates' lazy files: compile each with -recorder and keep what it opened from the lazy bundles.
tmp = tempfile.mkdtemp(prefix='bundles-v5-')
subprocess.run(['npx', 'esbuild', os.path.join(HERE, '../web/static/lib/templates.ts'), '--bundle', '--format=esm',
                '--platform=node', '--log-level=warning', '--outfile=' + os.path.join(tmp, 'tpl.mjs')], check=True, cwd=HERE)
templates = json.loads(subprocess.run(['node', '-e', f"import('{tmp}/tpl.mjs').then(m => console.log(JSON.stringify([...m.TEMPLATES, m.templateById('welcome')])))"],
                                      check=True, capture_output=True, text=True).stdout)
used = {}
for t in templates:
    d = os.path.join(tmp, t['id'])
    for f in t['files']:
        os.makedirs(os.path.dirname(os.path.join(d, f['path'])), exist_ok=True)
        open(os.path.join(d, f['path']), 'w').write(f['content'])
    main = t['main'][:-4]
    for _ in range(2):  # a second pass sets the table of contents and references in their real fonts
        subprocess.run(['pdflatex', '-recorder', '-interaction=nonstopmode', main], cwd=d, capture_output=True)
    for line in open(os.path.join(d, main + '.fls'), errors='replace'):
        if line.startswith('INPUT ' + TL):
            path = '/texlive/' + line[len('INPUT ' + TL):].strip()
            if manifest.get(path, {}).get('bundle') in LAZY:
                used.setdefault(path, set()).add(t['id'])
shutil.rmtree(tmp)
prefetch = sorted(used)
json.dump(prefetch, open(os.path.join(HERE, 'src/prefetch.json'), 'w'), indent=0)
print(f"{len(prefetch)} font files prefetched ({sum(manifest[p]['end'] - manifest[p]['start'] for p in prefetch) / 1e6:.2f} MB)")
