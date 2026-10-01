#!/usr/bin/env bash
# Rebuild the Foldback demo video end to end. See README.md.
#   FOLDBACK_DEMO_WORK  working folder for model, audio, frames (default ${TMPDIR:-/tmp}/foldback-demo-work)
#   FOLDBACK_DEMO_OUT   output folder (default ./out next to this script)
#   FOLDBACK_APP        the app to record (default ../../index.html relative to this script)
#   VOICE, SPEED        Kokoro voice and speed (default bf_emma 1.06)
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
export FOLDBACK_DEMO_WORK="${FOLDBACK_DEMO_WORK:-${TMPDIR:-/tmp}/foldback-demo-work}"
export FOLDBACK_DEMO_OUT="${FOLDBACK_DEMO_OUT:-$SRC/out}"
mkdir -p "$FOLDBACK_DEMO_WORK" "$FOLDBACK_DEMO_OUT"
if [ ! -f "$FOLDBACK_DEMO_WORK/tts/voices.npz" ] || [ ! -f "$FOLDBACK_DEMO_WORK/tts/kokoro-q8.onnx" ]; then "$SRC/setup_tts.sh"; fi
python3 "$SRC/tts.py" "${VOICE:-bf_emma}" "${SPEED:-1.06}"
NODE_PATH="${NODE_PATH:-$(npm root -g)}" node "$SRC/record.js"
python3 "$SRC/combine.py"
"$SRC/make_web.sh"
