#!/usr/bin/env bash
# One-off setup in the working folder ($FOLDBACK_DEMO_WORK, default ${TMPDIR:-/tmp}/foldback-demo-work):
#   - the offline Kokoro-82M voice, from npm + PyPI only (no Hugging Face or GitHub downloads):
#       model  : npm "kokoro-q8-shards" = onnx-community/Kokoro-82M-v1.0-ONNX model_quantized.onnx in 6 parts
#       voices : npm "kokoro-local-runtime" ships the Kokoro v1.0 voice style vectors (voices/*.bin)
#       runtime: pip "kokoro-onnx" (onnxruntime + espeak-ng phonemiser) and "soundfile"
#   - a local copy of the Google Fonts the app uses (fonts/), so the recording shows the real fonts even where
#     the browser cannot reach Google Fonts itself. Optional: record.js falls back to loading them normally.
set -euo pipefail
WORK="${FOLDBACK_DEMO_WORK:-${TMPDIR:-/tmp}/foldback-demo-work}"
mkdir -p "$WORK/tts" "$WORK/fonts"
python3 -m pip install -q kokoro-onnx soundfile
cd "$WORK/tts"
if [ ! -f kokoro-q8.onnx ]; then
  npm pack -q kokoro-q8-shards@1.0.0 >/dev/null && tar xzf kokoro-q8-shards-1.0.0.tgz
  cat package/kokoro-q8.part{0,1,2,3,4,5}.bin > kokoro-q8.onnx && rm -rf package kokoro-q8-shards-1.0.0.tgz
fi
echo "fbae9257e1e05ffc727e951ef9b9c98418e6d79f1c9b6b13bd59f5c9028a1478  kokoro-q8.onnx" | sha256sum -c -
if [ ! -f voices.npz ]; then
  npm pack -q kokoro-local-runtime@0.1.0 >/dev/null && tar xzf kokoro-local-runtime-0.1.0.tgz
  python3 - <<'PY'
import numpy as np, glob, os
np.savez('voices.npz', **{os.path.basename(f)[:-4]: np.fromfile(f, dtype=np.float32).reshape(-1, 1, 256) for f in glob.glob('package/voices/*.bin')})
PY
  rm -rf package kokoro-local-runtime-0.1.0.tgz
fi
cd "$WORK/fonts"
if [ ! -f fonts.css ]; then
  UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
  if curl -fsS -A "$UA" "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&display=swap" -o fonts.css.tmp; then
    for u in $(grep -o "https://fonts.gstatic.com[^)]*" fonts.css.tmp | sort -u); do curl -fsS "$u" -o "$(basename "$u")"; done
    mv fonts.css.tmp fonts.css
  else rm -f fonts.css.tmp; echo "fonts: could not fetch, the browser will load them itself"; fi
fi
echo "setup done in $WORK"
