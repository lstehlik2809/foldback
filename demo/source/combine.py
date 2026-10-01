#!/usr/bin/env python3
"""Combine the screencast frames ($WORK/frames.json, wall-clock times) with the narration clips placed at the times in
$WORK/timeline.json, normalise loudness to -16 LUFS (two-pass loudnorm), and write to the output folder:
foldback-demo.mp4, foldback-demo.srt (captions) and narration.md (the script with timestamps).
Env: FOLDBACK_DEMO_WORK (default <tmp>/foldback-demo-work), FOLDBACK_DEMO_OUT (default ./out next to this script)."""
import json, os, re, subprocess, tempfile, numpy as np, soundfile as sf
SRC = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get('FOLDBACK_DEMO_WORK') or os.path.join(tempfile.gettempdir(), 'foldback-demo-work')
OUT = os.environ.get('FOLDBACK_DEMO_OUT') or os.path.join(SRC, 'out')
os.makedirs(OUT, exist_ok=True)
run = lambda *a: subprocess.run(a, check=True, capture_output=True, text=True)
tl = json.load(open(os.path.join(WORK, 'timeline.json')))
fr = json.load(open(os.path.join(WORK, 'frames.json')))

# 1. video: every screencast frame shown from its own wall-clock time (relative to t0) until the next one
frames = [x for x in fr['frames']]
# frames that arrived before t0 collapse onto t=0 (keep the latest of them)
pre = [x for x in frames if x['t'] <= 0]; frames = ([dict(pre[-1], t=0.0)] if pre else []) + [x for x in frames if x['t'] > 0]
if frames[0]['t'] > 0: frames[0] = dict(frames[0], t=0.0)
end = tl['total'] + 0.3
lst = os.path.join(WORK, 'frames.txt')
with open(lst, 'w') as f:
    for x, y in zip(frames, frames[1:] + [{'t': end}]):
        d = max(0.001, min(y['t'], end) - x['t'])
        if x['t'] >= end: break
        f.write(f"file '{x['f']}'\nduration {d:.4f}\n")
    f.write(f"file '{frames[-1]['f']}'\n")
print('frames used', len(frames))
# 2. narration track
sr = 24000; total = tl['total'] + 0.3
track = np.zeros(int(total * sr), dtype=np.float32)
for s in tl['segments']:
    a, r = sf.read(s['file'], dtype='float32'); assert r == sr
    i = int(s['start'] * sr); track[i:i + len(a)] += a[:len(track) - i]
raw = os.path.join(WORK, 'narration-raw.wav'); sf.write(raw, track, sr)
# two-pass loudnorm to -16 LUFS
st = subprocess.run(['ffmpeg', '-hide_banner', '-i', raw, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'], capture_output=True, text=True).stderr
j = json.loads(st[st.rindex('{'):st.rindex('}') + 1])
af = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}"
      f":measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true,aresample=48000")

# 3. mux
mp4 = os.path.join(OUT, 'foldback-demo.mp4')
run('ffmpeg', '-y', '-hide_banner', '-f', 'concat', '-safe', '0', '-i', lst, '-i', raw, '-t', f'{total:.3f}',
    '-map', '0:v', '-map', '1:a', '-vf', 'fps=30,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-tune', 'stillimage',
    '-af', af, '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', mp4)
print(run('ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,codec_name,width,height', '-of', 'compact', mp4).stdout)

# 4. subtitles + script
def ts(t, srt=True):
    h, rem = divmod(t, 3600); mnt, sec = divmod(rem, 60)
    return f'{int(h):02}:{int(mnt):02}:{int(sec):02},{int(round((sec % 1) * 1000)) % 1000:03}' if srt else f'{int(mnt)}:{int(sec):02}'
def wrap(t, n=46):
    words, lines, cur = t.split(), [], ''
    for w in words:
        if cur and len(cur) + 1 + len(w) > n: lines.append(cur); cur = w
        else: cur = (cur + ' ' + w).strip()
    lines.append(cur); return lines
def pieces(text):
    """Sentences; a sentence too long for two lines is split after commas or semicolons (never after a colon)."""
    out = []
    for sent in re.split(r'(?<=[.?!])\s+', text.strip()):
        if len(wrap(sent)) <= 2: out.append(sent); continue
        cur = ''
        for x in re.split(r'(?<=[,;])\s+', sent):
            if cur and len(wrap(cur + ' ' + x)) > 2: out.append(cur); cur = x
            else: cur = (cur + ' ' + x).strip()
        out.append(cur)
    return out
MIN_CUE = 1.5  # seconds: shorter cues are merged into a neighbour
cues = []
for s in tl['segments']:
    chunks, cur = [], ''
    for x in pieces(s['text']):  # pack into cues of at most two lines
        if cur and len(wrap(cur + ' ' + x)) > 2: chunks.append(cur); cur = x
        else: cur = (cur + ' ' + x).strip()
    chunks.append(cur)
    n = sum(len(c) for c in chunks); seg = []; t = s['start']
    for c in chunks:
        d = s['dur'] * len(c) / n; seg.append([t, t + d, c]); t += d
    # merge a cue that is too short, or that ends on a colon, into the next one (the last one into the previous)
    i = 0
    while len(seg) > 1 and i < len(seg):
        a, b, c = seg[i]
        if b - a < MIN_CUE or c.rstrip().endswith(':'):
            j = i + 1 if i + 1 < len(seg) else i - 1; lo, hi = sorted((i, j))
            seg[lo:hi + 1] = [[seg[lo][0], seg[hi][1], seg[lo][2] + ' ' + seg[hi][2]]]; i = 0
        else: i += 1
    cues += [(a, b, '\n'.join(wrap(c))) for a, b, c in seg]
with open(os.path.join(OUT, 'foldback-demo.srt'), 'w') as f:
    for i, (a, b, txt) in enumerate(cues, 1): f.write(f'{i}\n{ts(a)} --> {ts(b)}\n{txt}\n\n')
segs = json.load(open(os.path.join(SRC, 'narration.json'))); part = {s['id']: s['part'] for s in segs}
md = ['# Foldback demo: narration script', '',
      'Voice-over for `foldback-demo.mp4` (about %s). Timestamps are when each line starts in the final video; '
      'the italic line under each says what is on screen. To re-record in your own voice, read each line at its timestamp '
      '(or edit `narration.json` and run `run.sh` again).' % ts(total, False), '']
cur = None
for s in tl['segments']:
    if part[s['id']] != cur: cur = part[s['id']]; md += ['', f'## {cur}', '']
    md.append(f"**[{ts(s['start'], False)}]** {s['text']}  ")
    if s.get('screen'): md.append(f"_On screen: {s['screen']}_")
    md.append('')
open(os.path.join(OUT, 'narration.md'), 'w').write('\n'.join(md) + '\n')
print('wrote srt with', len(cues), 'cues; shortest', round(min(b - a for a, b, _ in cues), 2), 's; outputs in', OUT)
