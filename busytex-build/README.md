# Rebuilding busytex.wasm

The in-browser engine runs `busytex`: one multi-call WebAssembly binary holding pdfTeX, XeTeX, LuaHBTeX, bibtex8,
xdvipdfmx, makeindex and the kpathsea tools, picked by `argv[0]`. We take it prebuilt from Siglum
(`site/v1/busytex.js` + `busytex.wasm`, served Brotli-compressed as `/v2/busytex.wasm`). This folder rebuilds it from
source, natively on this Mac, so we control its build flags and, later, the engines themselves.

## Results (2026-10-24)

- **The build works natively on Apple Silicon.** `./build.sh all` takes about 27 minutes on this (shared, loaded) M4,
  most of it in TeX Live's configure scripts and ICU. No Linux, container or cloud machine needed. It needs about 3 GB
  of disk (2.6 GB of work files, plus a transient 0.3 GB emsdk download).
- **It is reproducible.** A clean `./build.sh all` gave bit-identical outputs (SHA-256) to the build tested here.
- **It is a drop-in replacement.** Built with Siglum's flags, our `busytex.js` is byte-identical to the shipped one,
  and the wasm has identical imports, exports, memory limits and memory layout. Typeset output is identical: the same
  four documents (pdfLaTeX, TikZ/pgfplots, BibTeX, XeLaTeX/fontspec) give the same PDFs as the shipped binary,
  timestamps, IDs and font subset tags aside.
- **A 4 MB C stack** (`STACK_SIZE=4194304`, upstream default 64 KB) lets LuaTeX build the LuaLaTeX format, which
  overflows the shipped binary's stack ("Stack overflow detected"); 45/45 coverage, same time as the shipped binary.

## What `out/` is (2026-10-25): the build that ships at `/v4/`

`OPT=-O3 LINK_OPT=-O3 ./build.sh all`: the C compiled `-O3` (upstream `-Oz`), Binaryen's optimizer at link (upstream
none), the 4 MB stack, snapshot points in pdfTeX, XeTeX and LuaTeX, and native pgfmath in pdfTeX and XeTeX
(`patch-snapshot.py`, `../native/pgfmath.c`). `busytex.wasm` 30,758,496 bytes, `busytex.wasm.br` 8.46 MB (8.13 MB at
`-Oz` before native pgfmath), `busytex.js` 158,861 bytes (minified by the `-O3` link; same exports).

- **Speed:** `-O3` buys 5-8% on pgfplots and nothing measurable on LuaLaTeX (a unicode-math document: 3.6 s either
  way, against 0.7 s for native LuaLaTeX). The time wasn't in the engine's code generation: half of it was the engine
  restarting TeX for bundles it fetched one at a time (fixed in the compiler, item 14: 3.6 s -> 1.9 s).
- **Snapshots:** at the top of each engine's main loop (`big_switch`), once TeX has read past `\begin{document}` and
  after each shipped page, the engine calls `Module.clearsnapPoint`; `clearsnap_<engine>_resume(mainpos)` re-enters the
  main loop from a restored copy of memory (`../patch-worker-snapshot.js` takes and restores the copies). pdfTeX's and
  XeTeX's C is web2c output, patched after generation (the Makefile rules make `<engine>d.h`, run the patch, then
  compile); LuaTeX's `luatexdir/tex/maincontrol.c` is patched in the source tree (originals kept as `.orig`).
  `qa/engine-snapshot.mjs`: an edit near the end of a 36-page document with a plot per section recompiles in 1.3 s
  instead of 6.6 s, a LuaLaTeX unicode-math edit in 0.8 s instead of 2.7 s, and every resumed PDF matches a full
  compile.

## What we ship (and what built it)

| | |
|---|---|
| Binary | `site/v1/busytex.wasm`, 30,767,701 bytes (Brotli: `build/busytex.wasm.br`, 8,125,583) |
| Glue | `site/v1/busytex.js`, 298,998 bytes, unminified Emscripten glue |
| Build recipe | [SiglumProject/busytex](https://github.com/SiglumProject/busytex) at `fbaaee98` ("Update to TeX Live 2025", 2026-01-04), the `busytex` submodule of siglum-engine 0.1.4; a fork of [busytex/busytex](https://github.com/busytex/busytex). (Siglum's README credits AsciiHuang/busytex, but the submodule is this fork.) |
| Emscripten | 3.1.43. Siglum's `build-wasm.sh` runs `make` in the `emscripten/emsdk:3.1.43` container (source paths in the wasm start with `/work/`, the container mount) with x86_64-Linux helper tools from busytex release `build_native_ff0318af…` (TeX Live 2023 era). Our 3.1.43 glue is byte-identical to the shipped glue. |
| Sources | TeX Live 2025 (`texlive-source` tag `texlive-2025.0`): pdfTeX 1.40.27, XeTeX 0.999997, LuaHBTeX 1.22.0, kpathsea 6.4.1, ICU 76, xdvipdfmx 20250205; expat 2.5.0, fontconfig 2.13.96 |
| Compile flags | `-Oz` (`CFLAGS_OPT_wasm`); expat gets none (a typo in the Makefile: `CFLAGS_$*_OPT`) |
| Link flags | `--static -Wl,--unresolved-symbols=ignore-all -sINITIAL_MEMORY=64MB -sMAXIMUM_MEMORY=512MB -sALLOW_MEMORY_GROWTH=1 -sEXIT_RUNTIME=0 -sINVOKE_RUN=0 -sASSERTIONS=1 -sERROR_ON_UNDEFINED_SYMBOLS=0 -sFORCE_FILESYSTEM=1 -sLZ4=1 -sMODULARIZE=1 -sEXPORT_NAME=busytex -sEXPORTED_FUNCTIONS=[_main,_flush_streams] -sEXPORTED_RUNTIME_METHODS=[callMain,FS,ENV,LZ4,PATH]` (Makefile `OPTS_BUSYTEX_LINK_wasm`). No `-O` on the link, so no Binaryen optimization pass, and an unminified glue. |
| Defaults (not set) | `STACK_SIZE` 64 KB (Emscripten's default since 3.1.27). No ASYNCIFY. No WASM_BIGINT (i64 arguments are split: `dynCall_jiji` & co.). C++ exception catching off; `setjmp`/`longjmp` through JS `invoke_*` wrappers. No pthreads. |
| Layout | Stack first: the C stack is `[0, 64 KB)`, static data from 65,536 (24 MB, mostly ICU data), heap from ~32 MB. Memory and table exported, not imported. No custom sections (no names, no producers). |
| Interface | 84 imports (`env`, `wasi_snapshot_preview1`), 31 exports. The Siglum worker calls the `busytex(moduleConfig)` factory with `instantiateWasm`, `noInitialRun`, `preRun` (sets `ENV`), then uses `Module.FS`, `Module.callMain` and `Module._flush_streams`. |
| Not in the fork | The fork at `fbaaee98` doesn't link as committed: TeX Live 2025 added `is_bit_set`, `save_arith_error` and `output_can_end` (David Fuchs's 2024 fixes) to both pdfTeX and XeTeX, so the link fails on duplicate symbols. And the shipped banner reads "(TeX Live 2025)", while the Makefile configures `--with-banner-add=_busytexwasm`. So Siglum built from an uncommitted, patched tree. Their TL 2026 commit (`e701866`) renames pdfTeX's copies of those symbols; we do the same and drop the banner suffix. |
| Later upstream | The fork's main (TL 2026, `e701866`) links with `-sSTACK_SIZE=5242880`: Siglum raised the stack too. |

Why the stack matters: with the stack first, an overflow runs below address 0 and traps, and the glue reports
`Stack overflow detected. You can try increasing -sSTACK_SIZE (currently set to 65536)`. Building the LuaLaTeX format
does that in babel's `hyphen.cfg`/`luababel.def`. The prebuilt `luahblatex.fmt` in Siglum's bundles
(`fmt-lualatex`) can't stand in: the wasm rejects it ("Fatal format file error; I'm stymied"), presumably because it
was dumped by a native 64-bit busytex and LuaTeX formats aren't portable to wasm32. So LuaLaTeX in the browser needs
its format built in the browser, and that needs a bigger stack.

## How to rebuild

Prerequisites: Xcode command line tools, Homebrew `cmake gnu-sed make brotli`, Python 3, ~3 GB free. Everything
else (emsdk 3.1.43, sources) is fetched into `work/`. Builds run under `nice -n 10`.

```sh
cd busytex-build
./build.sh all          # = fetch, tools, wasm, link
OPT=-O3 LINK_OPT=-O3 ./build.sh all  # what ships (out/); plain `all` gives upstream's -Oz
STACK_SIZE=8388608 ./build.sh link    # another stack size: relink only, about a minute
./build.sh clean        # delete work/ (keeps out/)
```

| Stage | What | Time here |
|---|---|---|
| `fetch` | busytex fork at `fbaaee98`, emsdk 3.1.43 (native arm64), TeX Live 2025 source (534 MB), expat, fontconfig | 54 s |
| `tools` | native helper tools from the same TeX Live source: `tangle ctangle otangle tangleboot ctangleboot tie` and `web2c fixwrites splitup makecpool` (they turn the WEB/CWEB sources into C) and ICU 76's `icupkg`/`pkgdata` (they package ICU's data); put where busytex's `download-native` would put its Linux binaries | 1 min 38 s |
| `wasm` | busytex's `make wasm`: TeX Live configure under `emconfigure` (the slow part), the libraries (ICU, HarfBuzz, FreeType, fontconfig...), kpathsea, xdvipdfmx, bibtex8, makeindex, the three engines, the link | 23 min 39 s |
| `link` | relink with `-sSTACK_SIZE` into `out/` (keeps the upstream-flags link in `work/busytex/build/wasm/upstream/`) | 1 min 8 s |

`work/` holds the `-O3` build (2.6 GB). With `work/` in place,
iterations are quick: a flag change is a relink (~1 min); a change to an engine
recompiles web2c (delete its objects, `./build.sh wasm`, ~1 min, then `./build.sh link`).

### Differences from Siglum's container build, and why

- **Host tools built natively** from the TeX Live 2025 source, instead of busytex's x86_64-Linux binaries (TeX Live
  2023 era), which can't run here.
- **GNU make 4** (Homebrew): macOS's make 3.81 loses the `-e CFLAGS=...` overrides (values with quotes and parentheses)
  on their way to recursive makes, so bibtex8 lost its symbol renames. The container has make 4.3. **GNU sed** for the
  Makefile's `sed -i`.
- `CMAKE_POLICY_VERSION_MINIMUM=3.5`: CMake 4 refuses expat 2.5.0's `cmake_minimum_required` otherwise.
- `NM_native=true`: the Makefile prints `nm -D libkpathsea.a` as a debug aid; Apple's nm fails on wasm objects.
- `MAKE_wasm="emmake make -jN"`: the Makefile runs every library and engine build through `emmake make`, which drops
  make's jobserver, so they compiled one file at a time (in Siglum's build too).
- The two source fixes in the table above (pdfTeX symbol renames, no banner suffix), applied to the fork's Makefile.
- `STACK_SIZE` is passed at relink through `EMCC_CFLAGS`; every other flag is the Makefile's.

### How close it is to the shipped binary

| | shipped | ours, Siglum's flags | ours, 4 MB stack (`out/`) |
|---|---|---|---|
| `busytex.js` | 298,998 B | byte-identical | 299,000 B: only the STACK_SIZE in the overflow message differs |
| `busytex.wasm` | 30,767,701 B | 30,777,895 B | 30,806,167 B |
| imports / exports | 84 / 31 | identical (names and signatures) | identical |
| memory | 64 MB initial, 512 MB max | same | same |
| C stack | `[0, 64 KB)` | same | `[0, 4 MB)`; data from 4 MB, heap from ~36 MB |
| functions | 18,767 | 18,753 | 18,753 |
| static data | 24,176,488 B | +9,840 B | +9,840 B |

The data difference is the build path: 152 source paths are compiled in (assert messages), `/work/…` in the container
and 65 characters longer here (152 × 65 = 9,880 bytes). The 14 functions (0.07%) we can't attribute without symbol
names (the shipped wasm has none); candidates are the host-side differences above (macOS host triplet in configure,
TeX Live 2025 vs 2023 helper tools, CMake 4 for expat) and the exact patch Siglum used for the duplicate symbols. They
don't show in output: PDFs match, 45/45 match. A byte-exact copy would need Siglum's Linux container, their native
tools and their unpublished patch; it isn't needed for a drop-in replacement.

The 4 MB stack costs 4 MB of the 64 MB initial memory (which still holds data, stack and a 28 MB heap), +28 KB of wasm
(larger addresses in the code) and +7 KB Brotli-compressed.

## Next

- **Snapshots across reloads: done** (`../patch-worker-snapshot.js`, the store at the end): snapshots that saved at
  least 0.8 s of TeX's time are kept in the engine origin's private file system, deflated 64 KB chunks named by SHA-256
  (a LuaLaTeX unicode-math document: 32 MB on disk, read back in 0.34 s; its first compile after a reload takes 1.2 s
  instead of 2.7 s). Four documents are kept.
- **More snapshots:** take them inside `\input` files' long chapters (today only the main file's position is exact).
- **Engine work** (a native math primitive for pgfmath): edit the WEB change files or C sources under
  `work/busytex/source/texlive/texk/web2c`, rebuild web2c, relink. Keep both pdfTeX and XeTeX in mind: the busytex
  Makefile's `*_REDEFINE` lists rename per-engine globals so they can share one binary, and any new global that both
  engines define needs adding there.
