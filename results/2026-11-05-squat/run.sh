#!/usr/bin/env bash
# Re-runs the form-check tools for this video with the parameters used in analysis.md.
# Outputs land next to this script, in guides/ and bar/. Run from anywhere:
#   bash results/2026-11-05-squat/run.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
VIDEO="$HERE/IMG_0110.mov"

# Rep bottoms (s): lowest hip points, read from guides/hip-shoulder-timeline.png
"$PY" "$ROOT/tools/pose_guides.py" "$VIDEO" --reps 1.7,7.2,13.4,19.6 --fps 10

# Plate-hub box at 4.0 s; plate diameter 220 px standing (4.0 s), 250 px at the bottom (13.4 s)
"$PY" "$ROOT/tools/bar_path.py" "$VIDEO" --box-t 4.0 --box 465,225,100,105 --plate-cal 4.0:220,13.4:250
