#!/usr/bin/env bash
# Sets up the pose-guide tool: Python venv + YOLO11 pose weights.
# Safe to re-run: skips anything that is already in place.
# Usage (from anywhere):  bash tools/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VENV="${VENV:-.venv}"
MODEL="tools/models/yolo11x-pose.pt"
MODEL_URL="https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x-pose.pt"
MODEL_SHA256="013c43543b0751b8918486ba96e01ee44a59040683a07f96cc22bcc2cb7785f8"

echo "==> Python environment ($ROOT/$VENV)"
if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV"
  else
    python3 -m venv "$VENV"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  UV_LINK_MODE=copy uv pip install --python "$VENV/bin/python" -r tools/requirements.txt
else
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -r tools/requirements.txt
fi

# bar_path.py needs the CSRT tracker, which only ships in OpenCV's contrib build.
# ultralytics pulls in plain opencv-python; installing contrib on top (same
# version, no deps) replaces the cv2 module with the superset.
CV_VER="$("$VENV/bin/python" -c 'import importlib.metadata as m; print(m.version("opencv-python"))' 2>/dev/null || true)"
if ! "$VENV/bin/python" -c 'import cv2, sys; sys.exit(0 if hasattr(cv2, "TrackerCSRT_create") else 1)' 2>/dev/null; then
  echo "==> OpenCV contrib (for bar tracking)"
  PKG="opencv-contrib-python-headless${CV_VER:+==$CV_VER}"
  if command -v uv >/dev/null 2>&1; then
    UV_LINK_MODE=copy uv pip install --python "$VENV/bin/python" --reinstall --no-deps "$PKG"
  else
    "$VENV/bin/python" -m pip install --force-reinstall --no-deps "$PKG"
  fi
fi

sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

echo "==> Model weights ($MODEL)"
mkdir -p tools/models
if [ -f "$MODEL" ] && [ "$(sha256 "$MODEL")" = "$MODEL_SHA256" ]; then
  echo "    already present, checksum OK"
else
  curl -fL --retry 3 -o "$MODEL.part" "$MODEL_URL"
  if [ "$(sha256 "$MODEL.part")" != "$MODEL_SHA256" ]; then
    echo "    checksum mismatch, download corrupted?" >&2; rm -f "$MODEL.part"; exit 1
  fi
  mv "$MODEL.part" "$MODEL"
  echo "    downloaded, checksum OK"
fi

echo "==> Check"
"$VENV/bin/python" -c "import torch, cv2, ultralytics; assert hasattr(cv2, 'TrackerCSRT_create'), 'OpenCV contrib missing'; print('torch', torch.__version__, '| ultralytics', ultralytics.__version__, '| opencv', cv2.__version__, '+ contrib')"
echo "Done. Re-run the example check:  bash results/2026-11-05-squat/run.sh"
echo "      New checks: see \"Adding a new check\" in SETUP.md"
