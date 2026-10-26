# Clearsnap engine

The TeX engine that [Clearsnap](https://www.clearsnap.dev) runs in your browser: TeX Live 2025 compiled to
WebAssembly, and the code around it that fetches packages, typesets the document on your own device and returns the
PDF, the log and SyncTeX. The Clearsnap editor itself is not in this repository.

It builds on [Siglum](https://github.com/SiglumProject/siglum-engine) and
[busytex](https://github.com/busytex/busytex), whose binary holds pdfTeX, XeTeX, LuaHBTeX, bibtex8, xdvipdfmx,
makeindex and kpathsea in one WebAssembly module.

## What's here

| Path | What it is |
|---|---|
| `busytex-build/` | Builds `busytex.wasm` from the TeX Live 2025 source, natively on an Apple Silicon Mac. Its README has the details and measurements. |
| `busytex-build/patch-snapshot.py` | Changes to pdfTeX, XeTeX and LuaTeX: snapshot points in the main loop and resuming from them, and the hook for native pgfmath. |
| `native/pgfmath.c` | pgfmath's arithmetic in C, giving pgfmath's exact results, built into pdfTeX and XeTeX. With differential tests against pgfmath. |
| `fastpaths/` | TeX shortcuts for pgfmath, xcolor and tabularray, installed at `\begin{document}`, each giving the result the package's own code gives. |
| `src/runner.js`, `site/index.html` | The engine page the editor embeds in a hidden iframe. |
| `patch-siglum.py`, `patch-siglum-helpers.js`, `patch-shared.js` | Changes to Siglum's compiler: packages from the TeX Live 2025 mirror, caches, prefetch. |
| `patch-worker.py`, `patch-worker-*.js` | Changes to Siglum's worker: the TeX log, SyncTeX, fonts fetched one file at a time, formats, LuaLaTeX, snapshots. |
| `make-texlive.py`, `make-font-names.py` | Build the static TeX Live 2025 package mirror and its font-name index. |
| `make-bundles.py`, `make-deps.py`, `make-bundles-v5.py` | Build the bundle sets the engine loads first, starting from Siglum's v0.1.0 bundles. |
| `site/licenses/` | The license notices served with the engine. |

## Building

The engine binary (about 30 minutes; it needs Xcode's command line tools, Homebrew `cmake gnu-sed make brotli`,
Python 3 and 3 GB of disk; everything else is downloaded into `busytex-build/work/`):

```sh
cd busytex-build
OPT=-O3 LINK_OPT=-O3 ./build.sh all    # busytex.js, busytex.wasm and busytex.wasm.br in out/
```

The engine page:

```sh
npm install
./build.sh                              # site/runner.js, site/worker.js, site/pdf-lib.min.js
```

The package mirror and the bundles need TeX Live 2025 installed in `/usr/local/texlive/2025`:

```sh
python3 make-texlive.py                 # build/tl2025: one archive per TeX Live package
python3 make-font-names.py              # build/tl2025/bundles/font-names.json
```

## Licenses

The files written for Clearsnap are released under the GNU General Public License, version 2 or later (`LICENSE`),
the license of pdfTeX and LuaTeX. Copyright 2026 Benmore Technologies.

`busytex.wasm` combines pdfTeX, XeTeX, LuaHBTeX and the other TeX Live programs and libraries, each under its own
license; [NOTICE.md](NOTICE.md) lists them. Siglum, busytex and pdf-lib are under the MIT license.

Each [release](https://github.com/Benmore-Studio/clearsnap-engine/releases) holds the engine binary that
clearsnap.dev serves and the exact upstream sources it was built from.
