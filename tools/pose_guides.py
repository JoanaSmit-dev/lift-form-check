#!/usr/bin/env python3
"""Hip / shoulder guide overlays for squat videos.

For each rep, grabs frames from the bottom of the squat onward, detects the
shoulders and hips (YOLO11 pose), and draws:
  - a torso line (shoulder midpoint -> hip midpoint) with its angle from vertical
  - horizontal guides at the BOTTOM frame's hip (orange) and shoulder (cyan)
    height, carried across every frame of the strip
  - how far hips and shoulders have risen since the bottom (px)
It also plots hip vs shoulder height across the whole video, with each
ascent's torso lean compared to the expected maximum (the lean at that rep's
bottom); extra lean is shaded red and written to lean-vs-bottom.csv. A third
panel shows the hip-shoulder distance (vertical gap + 2D torso length); a
shrinking gap on the ascent is shaded and written to gap-vs-bottom.csv.
Frames whose 2D torso length is >15% off the median are treated as detection
glitches: marked with x and left out of the smoothed lean/gap stats.

Assumes a static camera (pixel heights are only comparable within one video).

Usage:
  .venv/bin/python tools/pose_guides.py videos/IMG_0110.mov --reps 1.7,7.2,13.4,19.6
  options: --step 0.4 --count 6 --fps 5 --out frames/guides
Pose detections are cached in <out>/poses-<video name>.json, so re-running (or resuming after a
timeout) skips frames that are already done.
"""
import argparse, json, math, os
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "yolo11x-pose.pt")
L_SH, R_SH, L_HIP, R_HIP = 5, 6, 11, 12
HIP_C, SH_C, TORSO_C = (0, 140, 255), (255, 200, 0), (60, 255, 60)  # BGR


def grab(cap, t):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, img = cap.read()
    if not ok:
        raise RuntimeError(f"no frame at {t}s")
    return img


def detect(model, img):
    r = model(img, verbose=False)[0]
    if r.keypoints is None or len(r.boxes) == 0:
        return None
    i = int(np.argmax((r.boxes.xywh[:, 2] * r.boxes.xywh[:, 3]).cpu().numpy()))
    kp = r.keypoints.data[i].cpu().numpy()  # (17, 3): x, y, conf

    def mid(a, b):
        w = kp[[a, b], 2]
        if w.sum() < 0.3:
            return None
        return [float((kp[[a, b], 0] * w).sum() / w.sum()), float((kp[[a, b], 1] * w).sum() / w.sum()),
                float(w.mean())]

    sh, hip = mid(L_SH, R_SH), mid(L_HIP, R_HIP)
    if sh is None or hip is None:
        return None
    return {"shoulder": sh, "hip": hip}


def torso_angle(p):
    dx = p["shoulder"][0] - p["hip"][0]
    dy = p["hip"][1] - p["shoulder"][1]
    return math.degrees(math.atan2(abs(dx), dy))  # 0 = upright


def dashed_hline(img, y, color, dash=18, gap=10, th=2):
    x = 0
    while x < img.shape[1]:
        cv2.line(img, (x, y), (min(x + dash, img.shape[1]), y), color, th, cv2.LINE_AA)
        x += dash + gap


def label(img, lines, org=(12, 12)):
    x, y = org
    for text, color in lines:
        (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)
        cv2.rectangle(img, (x - 6, y - 4), (x + w + 6, y + h + 8), (0, 0, 0), -1)
        cv2.putText(img, text, (x, y + h), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)
        y += h + 14


def annotate(img, p, ref, t):
    img = img.copy()
    hy, sy = int(ref["hip"][1]), int(ref["shoulder"][1])
    dashed_hline(img, hy, HIP_C)
    dashed_hline(img, sy, SH_C)
    s = tuple(int(v) for v in p["shoulder"][:2]); h = tuple(int(v) for v in p["hip"][:2])
    cv2.line(img, s, h, TORSO_C, 4, cv2.LINE_AA)
    cv2.circle(img, s, 9, SH_C, -1, cv2.LINE_AA); cv2.circle(img, s, 9, (0, 0, 0), 2)
    cv2.circle(img, h, 9, HIP_C, -1, cv2.LINE_AA); cv2.circle(img, h, 9, (0, 0, 0), 2)
    dh = ref["hip"][1] - p["hip"][1]; ds = ref["shoulder"][1] - p["shoulder"][1]
    label(img, [(f"t={t:.1f}s", (255, 255, 255)),
                (f"hip +{dh:.0f}px", HIP_C),
                (f"shoulder +{ds:.0f}px", SH_C),
                (f"torso {torso_angle(p):.0f} deg", TORSO_C)])
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--reps", required=True, help="bottom time of each rep, seconds, comma-separated")
    ap.add_argument("--step", type=float, default=0.4)
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--fps", type=float, default=5, help="sampling rate for the whole-video plot (0 = skip)")
    ap.add_argument("--out", default="frames/guides")
    ap.add_argument("--height", type=int, default=700)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.video))[0]
    cache_p = os.path.join(a.out, f"poses-{stem}.json")  # one cache per video
    cache = json.load(open(cache_p)) if os.path.exists(cache_p) else {}

    from ultralytics import YOLO
    model = YOLO(MODEL)
    cap = cv2.VideoCapture(a.video)
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)

    def pose(t):
        k = f"{t:.2f}"
        if k not in cache:
            cache[k] = detect(model, grab(cap, t))
            json.dump(cache, open(cache_p, "w"))
        return cache[k]

    bottoms = [float(x) for x in a.reps.split(",")]
    summary = []
    for n, b in enumerate(bottoms, 1):
        ts = [round(b + i * a.step, 2) for i in range(a.count)]
        ref = pose(ts[0])
        panels = []
        for t in ts:
            img, p = grab(cap, t), pose(t)
            img = annotate(img, p, ref, t) if (p and ref) else img
            s = a.height / img.shape[0]
            panels.append(cv2.resize(img, (int(img.shape[1] * s), a.height)))
            if p and ref:
                summary.append({"rep": n, "t": t, "hip_rise_px": round(ref["hip"][1] - p["hip"][1]),
                                "shoulder_rise_px": round(ref["shoulder"][1] - p["shoulder"][1]),
                                "torso_deg": round(torso_angle(p))})
        cv2.imwrite(os.path.join(a.out, f"rep{n}-ascent-guides.jpg"), np.hstack(panels),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])

    with open(os.path.join(a.out, "ascent-measurements.csv"), "w") as f:
        f.write("rep,t,hip_rise_px,shoulder_rise_px,torso_deg\n")
        for r in summary:
            f.write(f"{r['rep']},{r['t']},{r['hip_rise_px']},{r['shoulder_rise_px']},{r['torso_deg']}\n")

    if a.fps > 0:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ts = [round(i / a.fps, 2) for i in range(int(dur * a.fps))]
        rows = [(t, pose(t)) for t in ts]
        rows = [(t, p) for t, p in rows if p]
        T = [t for t, _ in rows]
        H = [-p["hip"][1] for _, p in rows]; S = [-p["shoulder"][1] for _, p in rows]
        A = [torso_angle(p) for _, p in rows]
        # Torso length on screen should be ~constant; frames where it jumps >15%
        # from the median are detection glitches and are left out of the stats.
        D = [math.hypot(p["hip"][0] - p["shoulder"][0], p["hip"][1] - p["shoulder"][1]) for _, p in rows]
        D_med = float(np.median(D))
        valid = [abs(d - D_med) <= 0.15 * D_med for d in D]

        def smooth(vals):  # 5-point median over valid frames only
            out = []
            for i in range(len(vals)):
                w = [vals[k] for k in range(max(0, i - 2), min(len(vals), i + 3)) if valid[k]]
                out.append(float(np.median(w)) if w else vals[i])
            return out
        Am = smooth(A)
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 8.5), sharex=True, height_ratios=[2, 1, 1])
        ax1.plot(T, H, color="#ff8c00", lw=2, label="hip height")
        ax1.plot(T, S, color="#00b4d8", lw=2, label="shoulder height")
        ax1.set_ylabel("height (px, up = higher)"); ax1.legend(loc="lower right", frameon=False)
        ax2.plot(T, A, color="#2a9d3c", lw=1, alpha=.35)
        ax2.plot(T, Am, color="#2a9d3c", lw=2, label="torso lean (smoothed)")
        ax2.set_ylabel("torso lean (deg)")

        # Expected lean on the way up: no more than at the bottom of the rep.
        # Dashed = bottom lean held from the bottom until standing (lean < 10 deg);
        # red = extra forward lean beyond it (chest dropping / hips rising first).
        lean_rows = []
        for n, b in enumerate(bottoms, 1):
            i0 = min(range(len(T)), key=lambda i: abs(T[i] - b))
            j = i0
            while j < len(T) - 1 and Am[j] > 10:
                j += 1
            seg_t, seg_a = T[i0:j + 1], Am[i0:j + 1]
            base = Am[i0]
            ax2.plot(seg_t, [base] * len(seg_t), color="#444", ls="--", lw=1.5,
                     label="expected max (lean at bottom)" if n == 1 else None)
            ax2.fill_between(seg_t, base, seg_a, where=[x > base for x in seg_a], interpolate=True,
                             color="#e63946", alpha=.35, lw=0, label="extra lean on ascent" if n == 1 else None)
            k = int(np.argmax(seg_a)); peak = seg_a[k]
            ax2.annotate(f"+{peak - base:.0f}\u00b0", (seg_t[k], peak), xytext=(0, 4),
                         textcoords="offset points", ha="center", va="bottom", fontsize=9, color="#c1121f")
            lean_rows.append((n, b, round(base), round(peak), round(peak - base), seg_t[k]))
        ax2.legend(loc="upper left", frameon=False, fontsize=8, ncol=3)
        ax2.set_ylim(top=max(Am) + 16)
        with open(os.path.join(a.out, "lean-vs-bottom.csv"), "w") as f:
            f.write("rep,bottom_t,lean_at_bottom_deg,peak_lean_deg,extra_deg,peak_t\n")
            for r in lean_rows:
                f.write(",".join(str(x) for x in r) + "\n")

        # Hip-shoulder distance. Vertical gap = how far the shoulders sit above the
        # hips; it shrinks when the hips rise faster than the shoulders. The 2D
        # distance (apparent torso length) should stay roughly constant, as a sanity
        # check on the detections. Dashed = vertical gap at the bottom of each rep;
        # red = gap smaller than that on the way up.
        G = [p["hip"][1] - p["shoulder"][1] for _, p in rows]
        Gm = smooth(G)
        ax3.plot(T, D, color="#9aa0a6", lw=1.5, label="2D distance (torso length)")
        bad = [i for i in range(len(T)) if not valid[i]]
        ax3.scatter([T[i] for i in bad], [D[i] for i in bad], marker="x", color="#555", s=22, zorder=3,
                    label=f"excluded glitch ({len(bad)})")
        ax3.plot(T, G, color="#7b2cbf", lw=1, alpha=.35)
        ax3.plot(T, Gm, color="#7b2cbf", lw=2, label="vertical gap (smoothed)")
        gap_rows = []
        for n, b in enumerate(bottoms, 1):
            i0 = min(range(len(T)), key=lambda i: abs(T[i] - b))
            j = i0
            while j < len(T) - 1 and Am[j] > 10:
                j += 1
            seg_t, seg_g = T[i0:j + 1], Gm[i0:j + 1]
            base = Gm[i0]
            ax3.plot(seg_t, [base] * len(seg_t), color="#444", ls="--", lw=1.5,
                     label="gap at bottom" if n == 1 else None)
            ax3.fill_between(seg_t, base, seg_g, where=[g < base for g in seg_g], interpolate=True,
                             color="#e63946", alpha=.35, lw=0, label="gap shrinks (hips catching up)" if n == 1 else None)
            k = int(np.argmin(seg_g)); low = seg_g[k]
            if low < base:
                ax3.annotate(f"\u2212{base - low:.0f}px", (seg_t[k], low), xytext=(0, -4),
                             textcoords="offset points", ha="center", va="top", fontsize=9, color="#c1121f")
            gap_rows.append((n, b, round(base), round(low), round(base - low), round(100 * (base - low) / base), seg_t[k]))
        ax3.set_ylabel("hip\u2013shoulder (px)"); ax3.set_xlabel("video time (s)")
        ax3.set_ylim(bottom=min(Gm) - 30, top=max(D) + 45)
        ax3.legend(loc="upper left", frameon=False, fontsize=8, ncol=3)
        ax3.set_title("Hip\u2013shoulder distance: a shrinking vertical gap on the way up = hips rising before the shoulders", loc="left", fontsize=9)
        with open(os.path.join(a.out, "gap-vs-bottom.csv"), "w") as f:
            f.write("rep,bottom_t,gap_at_bottom_px,min_gap_on_ascent_px,shrink_px,shrink_pct,min_t\n")
            for r in gap_rows:
                f.write(",".join(str(x) for x in r) + "\n")

        for b in bottoms:
            for ax in (ax1, ax2, ax3):
                ax.axvline(b, color="#999", ls=":", lw=1)
        for ax in (ax1, ax2, ax3):
            ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", alpha=.25)
        ax1.set_title("Hip vs shoulder height and torso lean (dotted = rep bottoms)", loc="left")
        ax2.set_title("Torso lean vs expected: should not exceed the bottom-position lean on the way up", loc="left", fontsize=9)
        fig.tight_layout(); fig.savefig(os.path.join(a.out, "hip-shoulder-timeline.png"), dpi=150)

    print(json.dumps(summary))


if __name__ == "__main__":
    main()
