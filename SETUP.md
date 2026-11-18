# Pose-guide tool: setup

`tools/pose_guides.py` finds the hips and shoulders in a squat video (YOLO11 pose model) and draws comparison guides. It also writes a hip/shoulder timeline and a CSV of measurements. For what the output means, see an analysis such as [`results/2026-11-05-squat/analysis.md`](results/2026-11-05-squat/analysis.md).

## What's in git and what isn't

| Path | In git? | Why |
|------|---------|-----|
| `tools/pose_guides.py`, `tools/setup.sh`, `tools/requirements.txt` | ✅ | source |
| `results/<check>/` | ✅ | one folder per form check: video, `analysis.md`, `run.sh`, `frames/`, `guides/`, `bar/` |
| `results/<check>/guides/poses-<video>.json` | ✅ | detection cache, small; saves re-running the model |
| `.venv/` | ❌ ignored | Python environment, built per machine (~1 GB on macOS, ~6 GB on Linux ARM) |
| `tools/models/` | ❌ ignored | model weights (118 MB), downloaded by setup |

## Layout

```
lift-form-check/
├── SETUP.md
├── tools/                    shared scripts (+ models/, ignored)
└── results/
    └── 2026-11-05-squat/     one folder per check: <date>-<lift>
        ├── IMG_0110.mov      the video
        ├── analysis.md       write-up
        ├── run.sh            exact commands + parameters for this video
        ├── frames/           stills picked for the write-up
        ├── guides/           pose_guides.py output
        └── bar/              bar_path.py output
```

Both tools write next to the video by default (`guides/` and `bar/` in the video's folder), so each check stays self-contained. `--out` still overrides this.

## Requirements

- macOS or Linux, `bash`, `curl`
- Python 3.9–3.12 (`python3 --version`). [`uv`](https://docs.astral.sh/uv/) is optional but makes installs much faster.
- About 1.5 GB free disk on macOS (more on Linux, where PyTorch includes GPU libraries)
- Internet access to PyPI and github.com, for the first setup only

## Setup

```bash
cd ~/lift-form-check
bash tools/setup.sh
```

The script:
1. creates `.venv/` (with `uv` if installed, otherwise `python3 -m venv`)
2. installs `tools/requirements.txt` (ultralytics, PyTorch, OpenCV, matplotlib)
3. downloads `tools/models/yolo11x-pose.pt` from the Ultralytics GitHub release and checks its SHA-256
4. prints the installed versions as a check

It's safe to re-run: it skips the venv and model if they're already there. To put the venv somewhere else, run `VENV=/path/to/venv bash tools/setup.sh`.

> **Moved or copied the folder?** Delete `.venv/` and run setup again. Python venvs store absolute paths and don't work after being moved.

## Adding a new check

```bash
cd ~/lift-form-check
mkdir -p results/2026-11-20-squat
cp ~/Downloads/IMG_0123.mov results/2026-11-20-squat/
cp results/2026-11-05-squat/run.sh results/2026-11-20-squat/   # then edit VIDEO and the parameters
```

1. **First pass:** timeline plus rough rep bottoms.
   ```bash
   .venv/bin/python tools/pose_guides.py results/2026-11-20-squat/IMG_0123.mov --reps 1,7,13 --fps 10
   ```
2. **Exact bottoms:** open `results/2026-11-20-squat/guides/hip-shoulder-timeline.png`, read the lowest points of the orange hip line, put them in `run.sh` with the bar box and calibration (see below), and run it. Re-runs are fast because detections are cached.
   ```bash
   bash results/2026-11-20-squat/run.sh
   ```
3. **Write-up:** add `analysis.md` (and any picked stills in `frames/`) to the same folder.

To re-run an existing check: `bash results/<check>/run.sh`.

## Running the tools directly

| Option | Default | Meaning |
|--------|---------|---------|
| `--reps` | required | bottom time of each rep (s), comma-separated |
| `--step` | 0.4 | seconds between frames in each ascent strip |
| `--count` | 6 | frames per strip |
| `--fps` | 5 | sampling rate for the whole-video timeline (`0` = skip) |
| `--out` | `guides/` next to the video | output folder |
| `--height` | 700 | strip height in px |

Outputs in `--out`: `repN-ascent-guides.jpg`, `hip-shoulder-timeline.png` (the lower panel compares each ascent's lean with that rep's bottom lean, extra shaded red), `ascent-measurements.csv`, `lean-vs-bottom.csv` and `gap-vs-bottom.csv` (from the timeline, so only when `--fps` > 0; the timeline's bottom panel shows hip–shoulder distance), `poses-<video>.json`.

Speed: about 1 s per frame on CPU, so a 25 s video at `--fps 10` takes about 4 minutes the first time. On Apple Silicon it may be faster.

## Barbell tracking (`tools/bar_path.py`)

```bash
.venv/bin/python tools/bar_path.py results/<check>/VIDEO.mov --box-t 4.0 --box X,Y,W,H \
    --plate-cal T1:PX1,T2:PX2
```

1. **Pick the box.** Choose a time when the bar is clearly visible (`--box-t`). Draw a rectangle around the **hub of the near plate**: where the sleeve meets the plate, with the collar and clip. Give it as `x,y,w,h` in full-size video pixels, with x/y at the top-left corner. Don't box the whole plate: its face is featureless and the tracker drifts across it. The frame sheets help with finding coordinates (frames are 696×1238 for this phone).
2. **Calibrate (optional, for mm and m/s).** Measure the near plate's diameter on screen (its long axis, in px) at two times, ideally once standing and once at the bottom. Pass them as `--plate-cal t1:px1,t2:px2`. Bumper plates are 450 mm (`--plate-mm` to change). Without calibration, outputs are in px.
3. **Check the track.** Open `bar-path.jpg` and confirm the paths sit on the plate hub. If they wander off, use a tighter box or a frame where the hub is clearer.

Outputs (in `bar/` next to the video, or `--out`): `bar-path-chart.png`, `bar-path.jpg`, `bar-timeline.png`, `bar-reps.csv`, `bar-track.csv`. Tracking runs at roughly real time on CPU (about 15–45 s for a 23 s video). `--track-scale 0.5` is faster but less precise.

This needs OpenCV's contrib build (for the CSRT tracker), which `tools/setup.sh` installs on top of the plain OpenCV that ultralytics brings in.

## Filming for best results

- The camera must not move (tripod or propped phone). The guide lines compare pixel heights between frames.
- Side-on at hip height, 3–4 m away, gives true torso angles. Other angles still work for comparing reps, but the angles are only 2D.

## Troubleshooting

- **`checksum mismatch`:** the download was interrupted. Re-run `bash tools/setup.sh`.
- **`OpenCV contrib missing` / `has no attribute 'TrackerCSRT_create'`:** run `bash tools/setup.sh` again. A later `pip install` probably replaced OpenCV with the plain build.
- **`No module named ...`:** you're using the system Python. Run with `.venv/bin/python`, or `source .venv/bin/activate` first.
- **Strips start before the real bottom:** the `--reps` times are too early. Use the lowest hip points from the timeline.
- **× marks on the timeline:** frames where the detected torso length jumps more than 15%, usually a mis-detection. They're left out of the lean and gap stats automatically. If many frames are marked, check the video (blur, occlusion, someone in front of the camera).
- **Guides on the wrong person** (someone walking past): the tool picks the largest person in the frame, so crop or trim the video.
