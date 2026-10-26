#!/bin/bash
# Rebuilds busytex.wasm + busytex.js (the engine Siglum ships: TeX Live 2025 compiled with Emscripten 3.1.43)
# from source, natively on an Apple Silicon Mac. See README.md for what this reproduces and how long it takes.
#
#   ./build.sh fetch    clone the busytex fork at the pinned commit, install emsdk 3.1.43, download the sources
#   ./build.sh tools    build the native helper tools (tangle, web2c, icupkg...) the cross build runs on the host
#   ./build.sh wasm     the busytex wasm build itself (the long step); output = upstream flags (64 KB C stack)
#   ./build.sh link     relink busytex.js/.wasm with our flags (STACK_SIZE) into out/; about a minute, no recompiling
#   ./build.sh all      all of the above
#   ./build.sh debug    relink with function names and runtime checks into out-debug/ (for finding crashes)
#   ./build.sh clean    delete the work tree (keeps out/)
#
# Environment: WORK (default ./work), JOBS (default 6), STACK_SIZE (default 4194304 = 4 MB), OUT (default ./out),
# OPT (the C optimization level for `wasm`, default -Oz as upstream), LINK_OPT (extra link flags for `link`, e.g. -O3
# to run Binaryen's optimizer, which upstream doesn't).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK:-$HERE/work}"
OUT="${OUT:-$HERE/out}"
OPT="${OPT:--Oz}"
LINK_OPT="${LINK_OPT:-}"
JOBS="${JOBS:-6}"
STACK_SIZE="${STACK_SIZE:-4194304}"
NICE="nice -n 10"

BUSYTEX_REPO=https://github.com/SiglumProject/busytex.git
BUSYTEX_COMMIT=fbaaee98ef8f2d3717a1b01ca4cea222fc33a82f   # siglum-engine's busytex submodule (TeX Live 2025)
EMSDK_VERSION=3.1.43
URL_texlive=https://github.com/TeX-Live/texlive-source/archive/refs/heads/tags/texlive-2025.0.tar.gz
URL_expat=https://github.com/libexpat/libexpat/releases/download/R_2_5_0/expat-2.5.0.tar.gz
URL_fontconfig=https://www.freedesktop.org/software/fontconfig/release/fontconfig-2.13.96.tar.gz

B="$WORK/busytex"
NT="$WORK/native-tools"
LOGS="$WORK/logs"

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 ($2)" >&2; exit 1; }; }
stamp() { echo "[$(date '+%H:%M:%S')] $*"; }

env_setup() {
  # GNU sed: the busytex Makefile patches sources with `sed -i` (GNU syntax). GNU make 4: macOS's make 3.81 drops
  # the `-e CFLAGS=...` overrides (values with quotes and parentheses) on their way to recursive makes, so bibtex8
  # lost its symbol renames. The Linux container has make 4.3.
  export PATH="/opt/homebrew/opt/make/libexec/gnubin:/opt/homebrew/opt/gnu-sed/libexec/gnubin:$PATH"
  # CMake 4 refuses expat 2.5.0's cmake_minimum_required(3.1...) without this.
  export CMAKE_POLICY_VERSION_MINIMUM=3.5
  # shellcheck disable=SC1091
  source "$WORK/emsdk/emsdk_env.sh" >/dev/null 2>&1
  [ "$(emcc --version | head -1 | awk '{print $10}')" = "$EMSDK_VERSION" ] || { echo "emcc is not $EMSDK_VERSION" >&2; exit 1; }
}

fetch() {
  need git "xcode-select --install"; need cmake "brew install cmake"; need gperf "xcode-select --install"
  [ -x /opt/homebrew/opt/gnu-sed/libexec/gnubin/sed ] || { echo "missing GNU sed: brew install gnu-sed" >&2; exit 1; }
  [ -x /opt/homebrew/opt/make/libexec/gnubin/make ] || { echo "missing GNU make 4: brew install make" >&2; exit 1; }
  mkdir -p "$WORK" "$LOGS"
  if [ ! -d "$B/.git" ]; then git clone -q "$BUSYTEX_REPO" "$B"; fi
  git -C "$B" checkout -q "$BUSYTEX_COMMIT"
  if [ ! -d "$WORK/emsdk/.git" ]; then git clone -q https://github.com/emscripten-core/emsdk.git "$WORK/emsdk"; fi
  (cd "$WORK/emsdk" && ./emsdk install "$EMSDK_VERSION" && ./emsdk activate "$EMSDK_VERSION") > "$LOGS/emsdk.log" 2>&1
  rm -rf "$WORK/emsdk/downloads"/*
  for s in texlive expat fontconfig; do
    [ -f "$B/source/$s.txt" ] && continue
    eval "url=\$URL_$s"
    mkdir -p "$B/source/$s"
    curl -fsSL "$url" | tar -xzf - -C "$B/source/$s" --strip-components=1
    (cd "$B" && find "source/$s" > "source/$s.txt")
  done
  stamp "fetch done"
}

# The cross build runs a few programs on the host: the WEB/CWEB tanglers and the Pascal-to-C converter (web2c) to
# generate the engines' C sources, and ICU's icupkg/pkgdata to package ICU's data. Upstream downloads x86_64-Linux
# binaries of these from a busytex release (`make download-native`); here they are built natively from the same
# TeX Live 2025 source and put at the paths that target creates.
tools() {
  mkdir -p "$NT" "$LOGS"
  local SRC="$B/source/texlive"
  cd "$NT"
  [ -f config.status ] || $NICE "$SRC/configure" --disable-all-pkgs --disable-shared --enable-static --disable-multiplatform \
      --disable-native-texlive-build --without-x CFLAGS=-O2 CXXFLAGS=-O2 > "$LOGS/native-configure.log" 2>&1
  for d in texk/kpathsea texk/web2c libs/icu; do
    [ -f "$d/config.status" ] && continue
    mkdir -p "$d"
    (cd "$d" && $NICE sh -c "$(sed "s,auxdir/auxsub,$d,g" ../../subsubdir-conf.cmd)") > "$LOGS/native-configure-${d//\//-}.log" 2>&1
  done
  $NICE make -j"$JOBS" -C texk/kpathsea > "$LOGS/native-kpathsea.log" 2>&1
  $NICE make -j"$JOBS" -C texk/web2c tangle ctangle otangle tie tangleboot ctangleboot \
      web2c/stamp-fixwrites web2c/stamp-splitup web2c/stamp-web2c web2c/stamp-makecpool > "$LOGS/native-web2c.log" 2>&1
  $NICE make -j"$JOBS" -C libs/icu > "$LOGS/native-icu.log" 2>&1
  local N="$B/build/native/texlive"
  mkdir -p "$N/texk/web2c/web2c" "$N/libs/icu/icu-build/bin" "$N/libs/freetype2/ft-build"
  for t in ctangle otangle tangle tangleboot ctangleboot tie; do cp "texk/web2c/$t" "$N/texk/web2c/"; done
  for t in fixwrites makecpool splitup web2c; do cp "texk/web2c/web2c/$t" "$N/texk/web2c/web2c/"; done
  cp libs/icu/icu-build/bin/icupkg libs/icu/icu-build/bin/pkgdata "$N/libs/icu/icu-build/bin/"
  stamp "native tools done"
}

wasm() {
  env_setup
  mkdir -p "$LOGS"
  cd "$B"
  # TeX Live 2025 added is_bit_set, save_arith_error and output_can_end (David Fuchs's 2024 fixes) to both pdfTeX and
  # XeTeX, so linking both into one binary fails on duplicate symbols. Rename pdfTeX's copies, as the fork's TL 2026
  # commit (e701866) does; the fork's TL 2025 commit doesn't, so Siglum's binary was linked from a patched tree.
  grep -q '^PDFTEX_REDEFINE = zisbitset ' Makefile ||
    sed -i 's/^PDFTEX_REDEFINE = /PDFTEX_REDEFINE = zisbitset savearitherror outputcanend /' Makefile
  # Siglum's binary was also configured without the Makefile's --with-banner-add=_busytexwasm: its banner (in logs and
  # in every pdfTeX PDF's /PTEX.FullBanner) reads "(TeX Live 2025)". Drop it so our output matches theirs byte for byte.
  sed -i 's/--with-banner-add="_busytex\$\*"//' Makefile
  # Snapshot points and resume (patch-snapshot.py): generate pdftex0.c and xetex0.c, patch them, then compile.
  grep -q 'CLEARSNAP_PATCH' Makefile || python3 - <<'PY'
s = open('Makefile').read()
for e, first in (('pdftex', '\t$(MAKE_$*) -C $(dir $@) pdftexd.h synctexdir/pdftex-synctex.o'),
                 ('xetex', '\t$(MAKE_$*) -C $(dir $@) synctexdir/xetex-synctex.o')):
    assert s.count(first) == 1, e
    opts = '$(OPTS_' + e.upper() + '_$*)'
    s = s.replace(first, f'\t$(MAKE_$*) -C $(dir $@) {e}d.h $(subst -Dmain=, -Dbusymain=, {opts})\n'
                         f'\tpython3 $(CLEARSNAP_PATCH) {e} $(dir $@){e}0.c\n' + first)
open('Makefile', 'w').write(s)
PY
  # LuaTeX's main loop is hand-written C, patched in the source tree (patch-snapshot.py keeps the original as .orig).
  python3 "$HERE/patch-snapshot.py" luatex "$B/source/texlive/texk/web2c/luatexdir/tex/maincontrol.c" > /dev/null
  # The same `make wasm` the Siglum container build runs (build-wasm.sh), minus download-native (see tools()).
  # NM_native is only used for a debug listing (`nm -D` of libkpathsea.a), which Apple's nm fails on wasm objects.
  # MAKE_wasm: the Makefile builds every library and engine with `emmake $(MAKE)`; emmake doesn't pass on make's
  # jobserver, so those builds ran one file at a time (upstream too). An explicit -j gives them their own job pool.
  MAKEFLAGS="-j$JOBS" $NICE make wasm NM_native=true MAKE_wasm="emmake make -j$JOBS" CFLAGS_OPT_wasm="$OPT" \
    CLEARSNAP_PATCH="$HERE/patch-snapshot.py" > "$LOGS/wasm.log" 2>&1
  stamp "wasm done ($OPT): $(ls -l build/wasm/busytex.wasm | awk '{print $5}') bytes"
}

link() {
  env_setup
  cd "$B"
  [ -f build/wasm/busytex.o ] || { echo "run ./build.sh wasm first" >&2; exit 1; }
  mkdir -p "$OUT"
  # Keep the upstream-flags link (64 KB stack) once, for comparison with what Siglum ships.
  if [ ! -f build/wasm/upstream/busytex.wasm ]; then
    mkdir -p build/wasm/upstream && cp build/wasm/busytex.js build/wasm/busytex.wasm build/wasm/upstream/
  fi
  # Relink only. EMCC_CFLAGS reaches the final em++ link; every other upstream flag stays as in the Makefile.
  rm -f build/wasm/busytex.js build/wasm/busytex.wasm
  EMCC_CFLAGS="-sSTACK_SIZE=$STACK_SIZE $LINK_OPT" $NICE make build/wasm/busytex.js CLEARSNAP_PATCH="$HERE/patch-snapshot.py" > "$LOGS/link.log" 2>&1
  cp build/wasm/busytex.js build/wasm/busytex.wasm "$OUT/"
  brotli -f -q 11 -o "$OUT/busytex.wasm.br" "$OUT/busytex.wasm" 2>/dev/null || true
  stamp "linked with STACK_SIZE=$STACK_SIZE $LINK_OPT -> $OUT"
}

# A debugging link of the same build: function names kept and Emscripten's runtime checks on, so a crash names the
# function it happened in. Writes out-debug/ (out/ is untouched). About a minute.
debug() {
  env_setup
  cd "$B"
  [ -f build/wasm/busytex.o ] || { echo "run ./build.sh wasm first" >&2; exit 1; }
  rm -f build/wasm/busytex.js build/wasm/busytex.wasm
  EMCC_CFLAGS="-sSTACK_SIZE=$STACK_SIZE --profiling-funcs -sASSERTIONS=2 -sSTACK_OVERFLOW_CHECK=2" $NICE make build/wasm/busytex.js > "$LOGS/link-debug.log" 2>&1
  mkdir -p "$HERE/out-debug"
  cp build/wasm/busytex.js build/wasm/busytex.wasm "$HERE/out-debug/"
  stamp "debug link -> $HERE/out-debug"
}

case "${1:-}" in
  fetch) fetch ;;
  tools) tools ;;
  wasm) wasm ;;
  link) link ;;
  all) fetch; tools; wasm; link ;;
  debug) debug ;;
  clean) rm -rf "$WORK" ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
