#!/bin/sh
# Builds the in-browser engine site (engine.clearsnap.dev) into site/: runner.js (Siglum's compiler, patched by
# patch-siglum.py), worker.js (Siglum's worker, patched by patch-worker.py) and pdf-lib.
#   ./build.sh
set -eu
[ $# -eq 0 ] || { echo "usage: ./build.sh" >&2; exit 1; }
cd "$(dirname "$0")"
python3 patch-siglum.py
npx esbuild src/runner.js --bundle --format=esm --platform=browser --target=es2020 --minify '--external:blake3-wasm/*' --outfile=site/runner.js
python3 patch-worker.py node_modules/@siglum/engine/src/worker.js site/worker.js
# The figure cache cuts pictures out of the PDF with pdf-lib (MIT), loaded by the worker when it needs it.
cp node_modules/pdf-lib/dist/pdf-lib.min.js site/pdf-lib.min.js
mkdir -p site/licenses && cp node_modules/pdf-lib/LICENSE.md site/licenses/pdf-lib.txt
