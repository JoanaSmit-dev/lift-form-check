#!/usr/bin/env python3
"""Barbell travel from a squat video.

Tracks the hub of the plate nearest the camera (OpenCV CSRT tracker, from
opencv-contrib)
and reports, per rep:
  - bar depth (how far it travels down), descent / ascent duration,
    average descent speed (depth / descent time)
  - ascent speed: average (distance / time), peak, and the sticking point =
    slowest moment between 20% and 80% of the way up
  - horizontal drift in the image
Outputs (in --out):
  bar-path.jpg      every rep's path drawn on a standing frame
  bar-path-chart.png  each rep's path, horizontal vs vertical at the same scale
  bar-timeline.png  bar height and vertical speed over the whole video
  bar-track.csv     per-frame position, height and speed
  bar-reps.csv      the per-rep numbers above

Real units: give two plate measurements with --plate-cal t1:px1,t2:px2 — the
plate's diameter in pixels (its long axis on screen) at two video times, e.g.
one standing and one at the bottom. The scale is interpolated with bar height,
because the plate looks bigger the closer it is to the camera. Without it,
everything is in pixels.

Usage:
  .venv/bin/python tools/bar_path.py videos/IMG_0110.mov --box-t 4.0 --box 465,225,100,105 \
      --plate-cal 4.0:220,13.4:250
  --box x,y,w,h  = rectangle around the plate HUB (where the sleeve meets the
                   plate, with the collar/clip) at time --box-t, in full-size video
                   pixels. Don't box the whole plate: its face is featureless and
                   the tracker drifts across it.

Assumes a static camera. Horizontal drift mixes forward/back and sideways
movement unless the camera is exactly side-on.
"""
import argparse, csv, os
import cv2
import numpy as np


def load_frames(path, scale):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = []
    while True:
        ok, im = cap.read()
        if not ok:
            break
        frames.append(cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1 else im)
    return frames, fps


def track(frames, i0, box):
    """CSRT from frame i0 forwards and backwards; returns centre (x, y) per frame."""
    def run(order):
        tr = cv2.TrackerCSRT_create()
        tr.init(frames[order[0]], box)
        out = {order[0]: box}
        for i in order[1:]:
            ok, b = tr.update(frames[i])
            out[i] = b if ok else out[order[order.index(i) - 1]]
        return out
    res = run(list(range(i0, len(frames))))
    res.update(run(list(range(i0, -1, -1))))
    return np.array([[res[i][0] + res[i][2] / 2, res[i][1] + res[i][3] / 2] for i in range(len(frames))])


def smooth(v, k=5):
    pad = np.pad(v, (k // 2, k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--box", required=True, help="x,y,w,h of the near plate at --box-t (full-size pixels)")
    ap.add_argument("--box-t", type=float, default=0.0)
    ap.add_argument("--plate-cal", help="t1:px1,t2:px2 plate diameter on screen at two times")
    ap.add_argument("--plate-mm", type=float, default=450, help="real plate diameter (bumper plates: 450)")
    ap.add_argument("--track-scale", type=float, default=1.0, help="downscale (<1) to track faster, at some precision cost")
    ap.add_argument("--out", default="frames/bar")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    s = a.track_scale
    frames, fps = load_frames(a.video, s)
    bx = tuple(int(round(float(v) * s)) for v in a.box.split(","))
    xy = track(frames, int(round(a.box_t * fps)), bx) / s          # back to full-size pixels
    n = len(xy); T = np.arange(n) / fps
    X, Y = smooth(xy[:, 0]), smooth(xy[:, 1])

    # ---- scale: mm per pixel as a function of bar height on screen
    if a.plate_cal:
        (t1, p1), (t2, p2) = [tuple(map(float, c.split(":"))) for c in a.plate_cal.split(",")]
        y1, y2 = Y[int(round(t1 * fps))], Y[int(round(t2 * fps))]
        mm_per_px = lambda y: a.plate_mm / (p1 + (y - y1) * (p2 - p1) / (y2 - y1))
        unit, k = "mm", 1.0
    else:
        mm_per_px = lambda y: 1.0
        unit, k = "px", 1.0
    y_top = np.percentile(Y, 5)                                    # standing bar height
    depth = np.array([(y - y_top) * mm_per_px((y + y_top) / 2) for y in Y])   # + = below standing
    drift = np.array([(x - X[0]) * mm_per_px(y) for x, y in zip(X, Y)])
    vy = -np.gradient(depth, 1 / fps) / (1000 if unit == "mm" else 1)        # + = bar moving up
    vunit = "m/s" if unit == "mm" else "px/s"

    # ---- reps: contiguous stretches deeper than 10% of the max depth
    active = depth > 0.10 * depth.max()
    reps, i = [], 0
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            if j - i > fps * 0.5:
                reps.append((i, j - 1))
            i = j
        else:
            i += 1

    rows = []
    for r, (i, j) in enumerate(reps, 1):
        b = i + int(np.argmax(depth[i:j + 1]))
        # start / end = when the bar is still (|speed| below 5% of the rep's peak
        # speed): walk back from the fastest point down, forward from the fastest point up
        lo = reps[r - 2][1] if r > 1 else 0
        hi = reps[r][0] if r < len(reps) else n - 1
        still = 0.05 * float(np.abs(vy[lo:hi + 1]).max())
        start = lo + int(np.argmin(vy[lo:b + 1]))           # fastest point down
        while start > lo and vy[start - 1] < -still:
            start -= 1
        pk = b + int(np.argmax(vy[b:hi + 1]))
        end = pk
        while end < hi and vy[end + 1] > still:
            end += 1
        top0, top1 = float(depth[start]), float(depth[end])
        d = float(depth[b]) - top0
        # ascent: average speed = distance / time; sticking point = slowest moment
        # in the middle of the ascent (20-80% of the way up)
        rise = (float(depth[b]) - depth[b:end + 1]) / max(float(depth[b]) - top1, 1e-6)
        mid = [b + m for m in range(len(rise)) if 0.2 <= rise[m] <= 0.8]
        st = min(mid, key=lambda q: vy[q]) if mid else b
        rows.append(dict(rep=r, start_t=round(float(T[start]), 2), bottom_t=round(float(T[b]), 2),
                         end_t=round(float(T[end]), 2), depth=round(d),
                         descent_s=round(float(T[b] - T[start]), 2), ascent_s=round(float(T[end] - T[b]), 2),
                         mean_down=round(d / max(float(T[b] - T[start]), 1e-6) / (1000 if unit == "mm" else 1), 3),
                         mean_up=round((float(depth[b]) - top1) / max(float(T[end] - T[b]), 1e-6) / (1000 if unit == "mm" else 1), 3),
                         peak_up=round(float(vy[b:end + 1].max()), 3),
                         sticking_t=round(float(T[st]), 2), sticking_speed=round(float(vy[st]), 3),
                         drift_range=round(float(drift[start:end + 1].max() - drift[start:end + 1].min()))))
        reps[r - 1] = (start, end)

    # ---- CSVs
    with open(os.path.join(a.out, "bar-track.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["t", "x_px", "y_px", f"depth_{unit}", f"drift_{unit}", f"v_up_{vunit.replace('/', '_per_')}"])
        for q in range(n):
            w.writerow([round(T[q], 3), round(X[q], 1), round(Y[q], 1), round(depth[q], 1), round(drift[q], 1), round(vy[q], 3)])
    with open(os.path.join(a.out, "bar-reps.csv"), "w", newline="") as f:
        cols = list(rows[0].keys()) if rows else []
        hdr = {"depth": f"depth_{unit}", "mean_down": f"mean_down_{vunit}", "mean_up": f"mean_up_{vunit}", "peak_up": f"peak_up_{vunit}",
               "sticking_speed": f"sticking_speed_{vunit}", "drift_range": f"drift_range_{unit}"}
        w = csv.writer(f); w.writerow([hdr.get(c, c) for c in cols])
        for r in rows:
            w.writerow([r[c] for c in cols])

    # ---- bar path drawn on a standing frame
    cap = cv2.VideoCapture(a.video); cap.set(cv2.CAP_PROP_POS_FRAMES, reps[0][0] if reps else 0); _, bg = cap.read()
    bg = cv2.addWeighted(bg, 0.55, np.zeros_like(bg), 0.45, 0)
    cols = [(255, 190, 0), (0, 200, 255), (60, 220, 60), (230, 80, 230), (80, 80, 255), (255, 255, 255)]
    for r, (i, j) in enumerate(reps):
        c = cols[r % len(cols)]
        b = i + int(np.argmax(depth[i:j + 1]))
        pts = np.stack([X[i:j + 1], Y[i:j + 1]], 1).astype(np.int32)
        cv2.polylines(bg, [pts[:b - i + 1]], False, c, 2, cv2.LINE_AA)                 # down: thin
        cv2.polylines(bg, [pts[b - i:]], False, c, 4, cv2.LINE_AA)                     # up: thick
        cv2.circle(bg, tuple(pts[b - i]), 7, c, -1, cv2.LINE_AA)
        q = int(round(rows[r]["sticking_t"] * fps))  # sticking point marker
        cv2.drawMarker(bg, (int(X[q]), int(Y[q])), c, cv2.MARKER_TILTED_CROSS, 18, 3)
        cv2.putText(bg, f"rep {r + 1}", (20, 50 + 40 * r), cv2.FONT_HERSHEY_SIMPLEX, 1.0, c, 3, cv2.LINE_AA)
    cv2.putText(bg, "thin = down, thick = up, dot = bottom, x = sticking point", (20, bg.shape[0] - 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(os.path.join(a.out, "bar-path.jpg"), bg, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # ---- timeline
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True)
    a1.plot(T, -depth, color="#264653", lw=2)
    a1.set_ylabel(f"bar height vs standing ({unit})")
    a2.axhline(0, color="#999", lw=1)
    a2.plot(T, vy, color="#2a9d8f", lw=2)
    a2.fill_between(T, 0, vy, where=vy > 0, color="#2a9d8f", alpha=.18, lw=0)
    a2.set_ylabel(f"vertical speed ({vunit}, + = up)"); a2.set_xlabel("video time (s)")
    for r in rows:
        for ax in (a1, a2):
            ax.axvline(r["bottom_t"], color="#999", ls=":", lw=1)
        q = int(round(r["bottom_t"] * fps))
        a1.annotate(f"{r['depth']} {unit}", (r["bottom_t"], -depth[q]), xytext=(0, -12), textcoords="offset points",
                    ha="center", fontsize=9)
        a2.annotate(f"avg {r['mean_up']}", (r["bottom_t"] + r["ascent_s"] / 2, r["peak_up"]), xytext=(0, 6),
                    textcoords="offset points", ha="center", fontsize=9, color="#1d6f66")
        a2.plot(r["sticking_t"], r["sticking_speed"], marker="v", color="#e63946", ms=8)
    a2.plot([], [], marker="v", color="#e63946", ls="", label="sticking point (slowest, 20-80% of the way up)")
    a2.legend(loc="lower left", frameon=False, fontsize=8)
    for ax in (a1, a2):
        ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", alpha=.25)
    a1.set_title("Barbell travel (dotted = bar bottoms)", loc="left")
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "bar-timeline.png"), dpi=150)

    # ---- bar path chart: drift vs height, same scale on both axes
    fig, ax = plt.subplots(figsize=(4.6, 7))
    hexc = ["#00bed2", "#ffc800", "#3cdc3c", "#e650e6", "#ff5050", "#888888"]
    for r, (i, j) in enumerate(reps):
        b = i + int(np.argmax(depth[i:j + 1])); c = hexc[r % len(hexc)]
        dx = drift[i:j + 1] - drift[i]; h = -(depth[i:j + 1] - depth[i])
        ax.plot(dx[:b - i + 1], h[:b - i + 1], color=c, lw=1.2, ls="--")
        ax.plot(dx[b - i:], h[b - i:], color=c, lw=2.4, label=f"rep {r + 1}")
        q = int(round(rows[r]["sticking_t"] * fps)) - i
        ax.plot(dx[q], h[q], marker="X", color=c, ms=9, mec="k", mew=.6)
    ax.set_aspect("equal"); ax.axvline(0, color="#999", lw=1, ls=":")
    ax.set_xlim(-150, 150) if unit == "mm" else None
    ax.set_xlabel(f"horizontal, in the image ({unit})"); ax.set_ylabel(f"height vs rep start ({unit})")
    ax.set_title("Bar path per rep\n(dashed = down, solid = up, X = sticking point)", loc="left", fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "bar-path-chart.png"), dpi=150)

    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
