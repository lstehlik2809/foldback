#!/usr/bin/env python3
"""Synthesise each narration line in narration.json with Kokoro-82M (offline).
Writes $WORK/audio/<id>.wav and $WORK/segments.json (the lines plus each clip's duration).
Usage: python3 tts.py [voice] [speed]   (default bf_emma 1.06; e.g. af_heart for a US voice)"""
import json, os, sys, tempfile, numpy as np, soundfile as sf
from kokoro_onnx import Kokoro
SRC = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get('FOLDBACK_DEMO_WORK') or os.path.join(tempfile.gettempdir(), 'foldback-demo-work')
voice = sys.argv[1] if len(sys.argv) > 1 else 'bf_emma'
speed = float(sys.argv[2]) if len(sys.argv) > 2 else 1.06
lang = 'en-gb' if voice[0] == 'b' else 'en-us'
k = Kokoro(os.path.join(WORK, 'tts', 'kokoro-q8.onnx'), os.path.join(WORK, 'tts', 'voices.npz'))
segs = json.load(open(os.path.join(SRC, 'narration.json')))
os.makedirs(os.path.join(WORK, 'audio'), exist_ok=True)
for s in segs:
    a, sr = k.create(s['text'], voice=voice, speed=speed, lang=lang)
    idx = np.where(np.abs(a) > 0.01)[0]  # trim near-silence at both ends, keep 60 ms
    if len(idx): a = a[max(0, idx[0] - int(.06 * sr)): idx[-1] + int(.06 * sr)]
    f = os.path.join(WORK, 'audio', s['id'] + '.wav'); sf.write(f, a, sr)
    s['file'] = f; s['dur'] = round(len(a) / sr, 3); print(s['id'], s['dur'])
json.dump(segs, open(os.path.join(WORK, 'segments.json'), 'w'), indent=1)
print('total speech', round(sum(s['dur'] for s in segs), 1), 's')
