# Notices

## The engine binary

`busytex.wasm` and `busytex.js` (served by clearsnap.dev at `engine.clearsnap.dev/v4/`) are built by
`busytex-build/build.sh` from TeX Live 2025 (`texlive-source` tag `texlive-2025.0`), the busytex build recipe at
commit `fbaaee98` of [SiglumProject/busytex](https://github.com/SiglumProject/busytex), expat 2.5.0 and fontconfig
2.13.96, with Emscripten 3.1.43, and with the changes in `busytex-build/patch-snapshot.py` and `native/pgfmath.c`
(GNU GPL, version 2 or later). Each part keeps its own license:

| Part | License |
|---|---|
| pdfTeX, LuaHBTeX, xdvipdfmx | GNU GPL, version 2 or later |
| bibtex8 | GNU GPL, version 1 or later |
| xpdf (inside pdfTeX) | GNU GPL, version 2 or 3 |
| libpaper | GNU GPL, version 2 |
| MetaPost library (inside LuaHBTeX) | GNU LGPL, version 3 or later |
| kpathsea, zziplib | GNU LGPL, version 2.1 or later (zziplib also MPL 1.1) |
| graphite2, TECkit | GNU LGPL, version 2.1 or later, among others |
| XeTeX, makeindex | X11-style permissive licenses |
| ICU | Unicode License v3 |
| HarfBuzz, Lua 5.3, LuaSocket, LuaFileSystem, luaffi, expat, fontconfig, busytex | MIT-style licenses |
| FreeType | The FreeType License |
| libpng, zlib | The libpng and zlib licenses |
| The FontForge library (inside LuaHBTeX) | BSD-style license |

The GNU license texts are in `site/licenses/`, and every part's full license is in the TeX Live source tree, next to
its source. Each
[release](https://github.com/Benmore-Studio/clearsnap-engine/releases) of this repository holds the binary and the
exact source archives it was built from.

## The engine page

`site/runner.js` and `site/worker.js` are built from [Siglum](https://github.com/SiglumProject/siglum-engine) 0.1.4
(MIT, Copyright 2026 Siglum Project) with the changes in this repository. `site/pdf-lib.min.js` is
[pdf-lib](https://github.com/Hopding/pdf-lib) 1.17.1 (MIT). Their license texts are in `site/licenses/`.

## TeX Live packages

The engine fetches TeX Live 2025's packages, fonts and formats, unchanged, from a mirror at
`engine.clearsnap.dev/tl2025/` and from Siglum's bundles. Each keeps its own license (the LaTeX Project Public License,
the GNU GPL, the SIL Open Font License and others, as TeX Live lists them). The mirror carries the files TeX reads;
their documentation and sources are in the TeX Live 2025 distribution, archived at
<https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/2025/>.
