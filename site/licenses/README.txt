Clearsnap engine: licenses and source

This site (engine.clearsnap.dev) serves the TeX engine that the Clearsnap editor runs in your browser.

Source code: https://github.com/Benmore-Studio/clearsnap-engine
  The engine's build scripts and every change made to TeX Live, busytex and Siglum, released under the
  GNU General Public License, version 2 or later. Each release there holds the engine binary served here
  and the exact source archives it was built from.

/v4/busytex.wasm, /v4/busytex.js
  TeX Live 2025 (pdfTeX, XeTeX, LuaHBTeX, bibtex8, xdvipdfmx, makeindex, kpathsea and their libraries)
  compiled to WebAssembly with the busytex build recipe. Each part keeps its own license: the GNU GPL
  (pdfTeX, LuaHBTeX, xdvipdfmx, bibtex8, xpdf, libpaper), the GNU LGPL (kpathsea, the MetaPost library,
  zziplib, graphite2, TECkit), and permissive licenses (XeTeX, makeindex, ICU, HarfBuzz, Lua, FreeType,
  libpng, zlib, expat, fontconfig, busytex). The list with versions is in NOTICE.md in the source
  repository. GPL-2.0.txt, GPL-3.0.txt, LGPL-2.1.txt and LGPL-3.0.txt here are the GNU license texts.

/runner.js, /worker.js
  Built from Siglum 0.1.4 (MIT, siglum-engine.txt and siglum-filesystem.txt) with Clearsnap's changes.

/pdf-lib.min.js
  pdf-lib 1.17.1 (MIT, pdf-lib.txt).

/tl2025/, /v1/ to /v5/
  TeX Live 2025's packages, fonts and formats, unchanged, each under its own license as TeX Live lists
  it. Their documentation and sources are in the TeX Live 2025 distribution:
  https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/2025/
