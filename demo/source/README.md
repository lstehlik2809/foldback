# Demo video: sources

These scripts rebuild `demo/foldback-demo.mp4` and the files that go with it. A headless browser drives the app at
`../../index.html`: the welcome window, the Sam example, then "Build it with me" on the Petra case and its results. An
offline neural voice reads `narration.json`. Each line starts with its on-screen actions, so voice and picture stay in sync.

## Requirements

- Node 18+ with Playwright and its Chromium (`npm i -g playwright && npx playwright install chromium`)
- Python 3.9+ with pip; ffmpeg and ffprobe; curl; npm (used only to fetch the voice model)

## One command

```sh
./run.sh
```

The first run calls `setup_tts.sh`, which downloads about 110 MB. Each run then takes about 5 minutes: the recording
plays in real time.

## Folders

| Variable | Default | Holds |
|---|---|---|
| `FOLDBACK_APP` | `../../index.html` (from this folder) | the app being recorded |
| `FOLDBACK_DEMO_WORK` | `$TMPDIR/foldback-demo-work` (or `/tmp/...`) | voice model, fonts, audio clips, frames (about 500 MB) |
| `FOLDBACK_DEMO_OUT` | `./out` next to these scripts | the finished files |

Outputs in `out/`:
- `foldback-demo.mp4` is the master: 1280×720, H.264 CRF 18, AAC, −16 LUFS.
- `foldback-demo-web.mp4` is the file to publish: H.264 High@4.0, faststart, 64 kbps mono.
- `foldback-demo.srt` and `foldback-demo.vtt` are the captions.
- `poster.jpg` is the first frame.
- `narration.md` is the script with timestamps.

To publish, copy the web MP4 (as `foldback-demo.mp4`), the VTT and the poster into `demo/`.

## The scripts

| File | What it does |
|---|---|
| `setup_tts.sh` | One-off setup. Installs `kokoro-onnx` from PyPI. Fetches the Kokoro-82M model from the npm package `kokoro-q8-shards` and checks its hash. Fetches the voices from `kokoro-local-runtime`. Saves a local copy of the app's Google Fonts. Nothing comes from Hugging Face or GitHub. |
| `tts.py [voice] [speed]` | Reads every line of `narration.json` aloud and records each clip's length. The default voice is `bf_emma` at speed 1.06; try `af_heart` for a US voice. |
| `record.js` | Drives the app with Playwright and captures frames with the Chrome DevTools screencast, which gives exact timestamps. It draws a cursor and highlight rings, and an end card with the address. `DRY=1` does a fast run without capture and prints the app's results. |
| `combine.py` | Builds the video from the frames, places each voice clip at the time it was spoken, normalises loudness, and writes the SRT and `narration.md`. |
| `make_web.sh` | Makes the web MP4, the VTT and the poster. |
| `run.sh` | Runs all of the above in order. |

## Editing the narration

- **Change the wording:** edit `text` in `narration.json`, then run `./run.sh`. Segments stretch to fit their voice
  clips, so wording changes need no timing changes.
- **Change what happens on screen:** each line has an `id`. `record.js` uses the same id in a `seg('<id>', actions)` call,
  where `actions` is what happens on screen while that line is spoken.
- **Add or remove a line:** do it in both `narration.json` and `record.js`.
- **Use your own voice:** read `out/narration.md` at its timestamps.
- **Check the result:** the app's numbers come from the app itself. If the example changes, run `DRY=1 node record.js`
  and update any figures the narration quotes.
