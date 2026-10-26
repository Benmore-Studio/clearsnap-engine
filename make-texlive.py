# Builds a static mirror of TeX Live 2025 (the engine's year) for the in-browser engine to fetch packages from on
# demand: one gzipped tar per TeX Live package (its runtime files, under texmf-dist/) at api/texlive/<package>, and
# bundles/file-to-package.json mapping every file name to its package. Served from engine.clearsnap.dev/tl2025/;
# nothing runs server-side, and each browser caches what it has fetched.
#   python3 make-texlive.py [texlive-root] [out-dir]
import gzip, io, json, os, sys, tarfile
from concurrent.futures import ProcessPoolExecutor

ROOT = sys.argv[1] if len(sys.argv) > 1 else '/usr/local/texlive/2025'
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build/tl2025')
# Run-time files only: documentation, sources, scripts and engine configuration aren't needed to typeset.
SKIP = ('texmf-dist/doc/', 'texmf-dist/source/', 'texmf-dist/scripts/', 'texmf-dist/web2c/', 'texmf-dist/tlpkg/',
        'texmf-dist/man/', 'texmf-dist/info/', 'texmf-dist/asymptote/', 'texmf-dist/xdvi/', 'texmf-dist/dvipdfmx/dvipdfmx.cfg')


def packages():
    """(name, [runfiles under texmf-dist]) for every TeX Live package with any."""
    name, files, inrun = None, [], False
    for line in open(os.path.join(ROOT, 'tlpkg/texlive.tlpdb'), encoding='utf-8'):
        if line.startswith('name '):
            if name and files:
                yield name, files
            name, files, inrun = line.split()[1], [], False
        elif line.startswith('runfiles'):
            inrun = True
        elif line.startswith(' ') and inrun:
            path = line.split()[0]
            if path.startswith('texmf-dist/') and not path.startswith(SKIP):
                files.append(path)
        elif not line.startswith(' '):
            inrun = False
    if name and files:
        yield name, files


def build(item):
    name, files = item
    buf = io.BytesIO()
    present = []
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT if all(len(f) < 100 for f in files) else tarfile.PAX_FORMAT) as tar:
        for f in files:
            full = os.path.join(ROOT, f)
            if not os.path.isfile(full):
                continue
            info = tar.gettarinfo(full, arcname=f)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = 0
            with open(full, 'rb') as fh:
                tar.addfile(info, fh)
            present.append(f)
    if not present:
        return name, [], 0
    data = gzip.compress(buf.getvalue(), compresslevel=9, mtime=0)
    with open(os.path.join(OUT, 'api/texlive', name), 'wb') as fh:
        fh.write(data)
    return name, present, len(data)


if __name__ == '__main__':
    os.makedirs(os.path.join(OUT, 'api/texlive'), exist_ok=True)
    os.makedirs(os.path.join(OUT, 'bundles'), exist_ok=True)
    pkgs = [(n, f) for n, f in packages() if '.' not in n and not n.startswith('00texlive')]
    index, total, count = {}, 0, 0
    with ProcessPoolExecutor() as pool:
        for name, present, size in pool.map(build, pkgs, chunksize=8):
            if not present:
                continue
            count += 1
            total += size
            for f in present:
                index.setdefault(os.path.basename(f), name)
    with open(os.path.join(OUT, 'bundles/file-to-package.json'), 'w') as fh:
        json.dump(index, fh, separators=(',', ':'), sort_keys=True)
    print(f'{count} packages, {total / 1e6:.0f} MB gzipped, {len(index)} file names -> {OUT}')
