#!/usr/bin/env bash
# Web delivery files in the output folder: foldback-demo-web.mp4 (H.264 High@4.0, faststart), foldback-demo.vtt, poster.jpg
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
OUT="${FOLDBACK_DEMO_OUT:-$SRC/out}"
cd "$OUT"
ffmpeg -y -v error -i foldback-demo.mp4 -c:v libx264 -preset veryslow -crf 26 -tune stillimage -profile:v high -level 4.0 -pix_fmt yuv420p -c:a aac -b:a 64k -ac 1 -movflags +faststart foldback-demo-web.mp4
{ echo "WEBVTT"; echo; sed -E 's/^([0-9:]+),([0-9]{3}) --> ([0-9:]+),([0-9]{3})$/\1.\2 --> \3.\4/' foldback-demo.srt | tr -d '\r'; } > foldback-demo.vtt
ffmpeg -y -v error -i foldback-demo.mp4 -frames:v 1 -q:v 4 poster.jpg
ls -la foldback-demo-web.mp4 foldback-demo.vtt poster.jpg
