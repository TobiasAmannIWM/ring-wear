"""ringwear.core — image loading, geometry detection, and wear segmentation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


# --------------------------------------------------------------------------- #
# Parameter (physikalische Einheiten -> auflösungsunabhängig)
# --------------------------------------------------------------------------- #
@dataclass
class Params:
    bar_um: float = 500.0            # Länge des Maßstabsbalkens
    um_per_px: float | None = None   # manuell; None = aus Maßstabsbalken
    nominal_area_mm2: float | None = 43.2  # Ringfläche lt. Zeichnung (optional)

    # Nominale Ringabmessungen (zur Berechnung der Analysegrenze)
    inner_diam_mm: float = 3.0   # nominaler Innendurchmesser / Bohrung (mm)
    outer_diam_mm: float = 8.0   # nominaler Außendurchmesser Ring (mm)

    # Ringgrenzen
    outer_margin_um: float = 100.0   # Sicherheitsabstand zur Außenkante (µm)
    inner_margin_um: float = 100.0   # Sicherheitsabstand zur Bohrungskante (µm)

    # Glättung / Kriterien
    smooth_sigma_um: float = 22.0
    local_bg_sigma_um: float = 190.0
    rim_band_um: float = 200.0
    local_contrast_thr: float = 1.15

    # Schwelle
    threshold_mode: str = "adaptive"  # "adaptive" | "fixed"
    threshold: float = 1.20           # bei fixed
    k_sigma: float = 1.30             # bei adaptive
    t_min: float = 1.08
    t_max: float = 1.35

    # Naht (Wechsel der Schleifrichtung)
    seam: str = "auto"                # "auto" | "none" | "prior"
    seam_prior_offset: float = 0.26   # Anteil von r_außen links der Mitte
    seam_search: tuple = (0.08, 0.45) # Suchbereich (Anteil r_außen links der Mitte)
    seam_min_step: float = 0.04       # min. rel. Helligkeitssprung für "erkannt"
    seam_gap_um: float = 20.0         # Pixel direkt an der Naht ausschließen

    # Morphologie
    open_um: float = 20.0
    close_um: float = 45.0
    min_area_um2: float = 5000.0

    # Texturkriterium: Verschleiß = Verschwinden der Schleifrillen
    tex_sigma_um: float = 44.0
    tex_low_thr: float = 0.42
    tex_min_rel: float = 0.70

    # Annotationsentfernung
    remove_annotations: bool = True

    sensitivity: tuple = field(default_factory=lambda: (1.10, 1.15, 1.20, 1.25))


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #
def fit_circle(x: np.ndarray, y: np.ndarray):
    """Algebraischer Kreisfit (Kasa) -> (cx, cy, r)."""
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    b = x ** 2 + y ** 2
    c = np.linalg.lstsq(A, b, rcond=None)[0]
    return float(c[0]), float(c[1]), float(np.sqrt(c[2] + c[0] ** 2 + c[1] ** 2))


def robust_circle(x, y, n_iter=4):
    c = fit_circle(x, y)
    keep = np.ones_like(x, bool)
    for _ in range(n_iter):
        res = np.hypot(x - c[0], y - c[1]) - c[2]
        mad = np.median(np.abs(res[keep])) + 0.5
        keep = np.abs(res) < 2.5 * mad
        if keep.sum() < 20:
            break
        c = fit_circle(x[keep], y[keep])
    res = np.hypot(x[keep] - c[0], y[keep] - c[1]) - c[2]
    return c, float(np.sqrt(np.mean(res ** 2))), int(keep.sum())


def norm_blur(img, weight, sigma):
    """Gauß-Glättung nur über Pixel mit weight>0 (normierte Faltung)."""
    w = weight.astype(float)
    num = cv2.GaussianBlur(img * w, (0, 0), sigma)
    den = cv2.GaussianBlur(w, (0, 0), sigma)
    return num / np.maximum(den, 1e-6)


def odd(n):
    n = max(1, int(round(n)))
    return n


def _parse_stem(stem: str) -> dict:
    """Extract test ID and all metadata from the filename.

    Supports three conventions (tried in order):
    1. Rich: {method}_T{N}_{ring}_{plate}_{cond}_{temp}C_{rot}_{geom}_{force}N_{area}mm2_ring
       e.g.  HTempGall_T1_INC625M_HX_dry_450C_R360_RP_6480N_43mm2_ring
    2. Old:  T{N}_{Material}[_{cond}]_{force}N[_{cond}]_{area}mm2_ring
       e.g.  T10_INC718_810N_43mm2_ring   or   T8_INC718_1620N_grinded_43mm2_ring
    3. Legacy: ring{N}_{Material}_{TX}
    """
    base = {
        "test": "", "material": "", "force_N": None, "area_mm2": None,
        "plate_material": None, "condition": None, "temperature_C": None,
        "rotation_deg": None, "geometry": None, "method_name": None,
    }

    # 1 — Rich convention
    m = re.match(
        r"^(?P<method>[A-Za-z][^_]*)_(?P<probe>T\d+)_(?P<ring>[^_]+)_"
        r"(?P<plate>[^_]+)_(?P<cond>[^_]+)_(?P<temp>-?\d+(?:\.\d+)?)C_"
        r"(?P<rot>R\d+)_(?P<geom>[^_]+)_(?P<force>\d+)N_(?P<area>\d+)mm2_ring",
        stem, re.IGNORECASE,
    )
    if m:
        return {**base,
                "test":           m.group("probe"),
                "material":       m.group("ring"),
                "force_N":        float(m.group("force")),
                "area_mm2":       float(m.group("area")),
                "plate_material": m.group("plate"),
                "condition":      m.group("cond"),
                "temperature_C":  float(m.group("temp")),
                "rotation_deg":   float(m.group("rot")[1:]),  # strip R prefix
                "geometry":       m.group("geom"),
                "method_name":    m.group("method"),
                }

    # 2 — Old convention (optional condition token before or after force/area)
    m = re.match(
        r"^(T\d+)_([A-Za-z0-9]+)_(\d+)N_(?:[A-Za-z][^_]*_)?(\d+)mm2_ring",
        stem, re.IGNORECASE,
    )
    if m:
        return {**base, "test": m.group(1), "material": m.group(2),
                "force_N": float(m.group(3)), "area_mm2": float(m.group(4))}

    # 3 — Legacy schema: ring{N}_{Material}_{TX}
    m = re.match(r"(ring\d+)_([A-Za-z0-9]+)_(T\d+)", stem, re.IGNORECASE)
    if m:
        return {**base, "test": m.group(3), "material": m.group(2)}

    return {**base}


# --------------------------------------------------------------------------- #
# 1. Laden & Vorverarbeitung
# --------------------------------------------------------------------------- #
def load_image(path: Path):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    rgb = np.array(im.convert("RGB"))
    # einfarbige Ränder (Folienüberschrift, weiße Streifen) abschneiden
    g = rgb.astype(float).mean(2)
    bgpix = (g > 240) | (g < 8)

    def trim(frac_rows):
        n = 0
        while n < len(frac_rows) // 3 and frac_rows[n] > 0.6:
            n += 1
        return n if n >= 3 else 0

    top = trim(bgpix.mean(1))
    bottom = trim(bgpix.mean(1)[::-1])
    left = trim(bgpix.mean(0))
    right = trim(bgpix.mean(0)[::-1])
    H, W = g.shape
    return rgb[top:H - bottom, left:W - right], top


def annotation_mask(rgb):
    r, g, b = [rgb[:, :, i].astype(int) for i in range(3)]
    red = (r > 150) & (g < 110) & (b < 110) & (r - np.maximum(g, b) > 80)
    blue = (b > 170) & (r < 100) & (b - r > 90)
    m = (red | blue).astype(np.uint8)
    if m.sum() == 0:
        return np.zeros(rgb.shape[:2], bool)
    return cv2.dilate(m, np.ones((7, 7), np.uint8)) > 0


# --------------------------------------------------------------------------- #
# 2. Maßstabsbalken
# --------------------------------------------------------------------------- #
def detect_scale_bar(rgb):
    """Weißes Kästchen unten rechts, darin längster dunkler horizontaler Balken."""
    gray = rgb.astype(float).mean(2)
    vmax = rgb.max(2)
    H, W = gray.shape
    y0, x0 = int(H * 0.75), int(W * 0.6)
    sub = gray[y0:, x0:]
    wl = np.percentile(sub, 99.5)
    white = (sub > 0.88 * wl).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(white)
    if n < 2:
        return None, None
    sh, sw = white.shape
    cand = []
    for i in range(1, n):
        bx, by, bw, bh, a = st[i]
        on_border = bx == 0 or by == 0 or bx + bw == sw or by + bh == sh
        if bw >= 15 and bh >= 8 and 1.2 < bw / bh < 10 and not on_border and a > 0.4 * bw * bh:
            cand.append((a, i))
    if not cand:
        return None, None
    bx, by, bw, bh = st[max(cand)[1], :4]
    dark = vmax[y0:, x0:][by:by + bh, bx:bx + bw] < 0.45 * wl
    best = (0, None)
    for row in range(bh):
        cols = np.nonzero(dark[row])[0]
        if len(cols) == 0:
            continue
        splits = np.split(cols, np.nonzero(np.diff(cols) > 1)[0] + 1)
        run = max(splits, key=len)
        if len(run) > best[0]:
            best = (len(run), (run[0], run[-1], row))
    if best[1] is None or best[0] < 0.4 * bw:
        return None, None
    c0, c1, row = best[1]
    length = c1 - c0 + 1
    return float(length), (x0 + bx, y0 + by, bw, bh)


# --------------------------------------------------------------------------- #
# 3. Ringgeometrie
# --------------------------------------------------------------------------- #
def detect_geometry(gray, excl):
    H, W = gray.shape
    g = cv2.GaussianBlur(gray.astype(float), (0, 0), 1.2)
    thr = min(55.0, np.percentile(g, 10))
    dark = ((g < thr) & ~excl).astype(np.uint8)
    k = max(3, int(round(min(H, W) / 70)) | 1)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    nb_, lab_bg, st_bg, _ = cv2.connectedComponentsWithStats(1 - dark)
    for i in range(1, nb_):
        x, y, w, h, a = st_bg[i]
        touches = x == 0 or y == 0 or x + w == W or y + h == H
        if not touches and a < 0.05 * H * W:
            dark[lab_bg == i] = 1
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(dark)
    best, score_best = None, -1
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 0.0005 * H * W:
            continue
        fill = a / (w * h)
        aspect = min(w, h) / max(w, h)
        dist = np.hypot(cen[i][0] - W / 2, cen[i][1] - H / 2) / min(H, W)
        score = a * fill * aspect * max(0.0, 1 - 2 * dist)
        if fill > 0.55 and aspect > 0.7 and score > score_best:
            best, score_best = i, score
    if best is None:
        raise RuntimeError("Bohrung nicht gefunden")
    hx, hy = cen[best]
    r_blob = np.sqrt(st[best, cv2.CC_STAT_AREA] / np.pi)

    def scan(cx, cy, lo, hi, mode):
        """Scan radial rays and return edge points.

        Rays that partially extend outside the image are clipped to their
        in-bounds portion instead of being skipped entirely.  This lets
        the outer-ring boundary be detected even when the ring nearly fills
        the frame.
        """
        X, Y = [], []
        min_pts = 2 if mode == "grad" else 1
        for th in np.linspace(0, 2 * np.pi, 360, endpoint=False):
            R = np.arange(lo, hi, 0.5)
            xs, ys = cx + R * np.cos(th), cy + R * np.sin(th)
            # Clip ray to in-bounds pixels instead of discarding the whole ray
            mask = (xs >= 1) & (xs <= W - 2) & (ys >= 1) & (ys <= H - 2)
            if mask.sum() < min_pts:
                continue
            xs, ys = xs[mask], ys[mask]
            xi, yi = xs.astype(int), ys.astype(int)
            if excl[yi, xi].mean() > 0.5:
                continue
            v = g[yi, xi]
            if mode == "grad":
                if len(v) < 2:
                    continue
                i = np.argmax(np.diff(v))
            else:
                i = np.argmin(v)
            X.append(xs[i]); Y.append(ys[i])
        return np.array(X), np.array(Y)

    X, Y = scan(hx, hy, 0.75 * r_blob, 1.4 * r_blob, "grad")
    if len(X) < 60:
        raise RuntimeError("Bohrungskante nicht erfassbar")
    hole, hole_rms, _ = robust_circle(X, Y)

    X, Y = scan(hole[0], hole[1], 2.3 * hole[2], 3.3 * hole[2], "min")
    ring_clipped = False
    if len(X) < 60:
        # Fallback: wider search range for rings close to the frame edge
        X, Y = scan(hole[0], hole[1], 2.0 * hole[2], 3.8 * hole[2], "min")
        ring_clipped = True
    if len(X) < 20:
        raise RuntimeError("Äußere Bildgrenze nicht erfassbar – Ring zu weit angeschnitten")
    outer, outer_rms, n_out = robust_circle(X, Y)
    return dict(hole=hole, outer=outer, hole_rms=hole_rms, outer_rms=outer_rms,
                outer_points=n_out, ring_clipped=ring_clipped)


# --------------------------------------------------------------------------- #
# 4. Naht (Wechsel der Schleifrichtung)
# --------------------------------------------------------------------------- #
def detect_seam(gs, ring, geo, upx, p: Params):
    cx, cy, ro = geo["outer"]
    hx, hy, rh = geo["hole"]
    H, W = gs.shape
    med = np.median(gs[ring])
    half = max(2, int(round(30 / upx)))
    xs = np.arange(int(cx - p.seam_search[1] * ro), int(cx - p.seam_search[0] * ro))
    pts = []
    for y0, y1 in [(cy - ro, hy - rh), (hy + rh, cy + ro)]:
        y0, y1 = int(max(0, y0)), int(min(H, y1))
        if y1 - y0 < 10:
            continue
        band = ring[y0:y1]
        vals = gs[y0:y1]
        prof = np.full(W, np.nan)
        for x in range(max(0, xs[0] - half), min(W, xs[-1] + half + 1)):
            col = band[:, x]
            if col.sum() >= 5:
                prof[x] = np.median(vals[col, x])
        step = np.array([(prof[x - half] - prof[x + half]) / med
                         if 0 <= x - half and x + half < W else np.nan for x in xs])
        if np.all(np.isnan(step)):
            continue
        i = int(np.nanargmax(step))
        pts.append((float(xs[i]), (y0 + y1) / 2, float(step[i])))
    found = [q for q in pts if q[2] >= p.seam_min_step]
    if len(found) == 2:
        (xa, ya, sa), (xb, yb, sb) = found
        if abs(xa - xb) < 0.12 * ro:
            return dict(x0=xa, y0=ya, x1=xb, y1=yb, status="detected",
                        strength=min(sa, sb))
    if len(found) >= 1:
        q = max(found, key=lambda t: t[2])
        return dict(x0=q[0], y0=0, x1=q[0], y1=H, status="partial",
                    strength=q[2])
    x = cx - p.seam_prior_offset * ro
    return dict(x0=x, y0=0, x1=x, y1=H, status="default (not detected)",
                strength=max([q[2] for q in pts], default=float("nan")))


# --------------------------------------------------------------------------- #
# 5./6. Segmentierung
# --------------------------------------------------------------------------- #
def analyse(path: Path, p: Params, outdir: Path, panel=False, font=None,
            sensitivity_grid=None, sensitivity_best=None):
    parsed = _parse_stem(path.stem)
    force_N   = parsed["force_N"]
    nom_area  = parsed["area_mm2"] if parsed["area_mm2"] is not None else p.nominal_area_mm2

    rgb, top = load_image(path)
    excl = annotation_mask(rgb) if p.remove_annotations else np.zeros(rgb.shape[:2], bool)
    work = cv2.inpaint(rgb, excl.astype(np.uint8), 5, cv2.INPAINT_TELEA) if excl.any() else rgb
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY).astype(float)
    H, W = gray.shape
    flags = []

    # Maßstab
    bar_px, bar_box = detect_scale_bar(rgb)
    if p.um_per_px:
        upx = p.um_per_px
    elif bar_px:
        upx = p.bar_um / bar_px
    else:
        raise RuntimeError("Maßstabsbalken nicht gefunden – bitte --um-per-px angeben")
    if bar_box is not None:
        x, y, w, h = bar_box
        excl[max(0, y - 3):y + h + 3, max(0, x - 3):x + w + 3] = True

    geo = detect_geometry(gray, excl)
    cx, cy, ro = geo["outer"]
    hx, hy, rh = geo["hole"]
    if geo.get("ring_clipped"):
        flags.append("outer boundary: fallback range used (ring near frame edge)")
    if geo["outer_rms"] > 3 or geo["hole_rms"] > 3:
        flags.append("circle fit inaccurate")
    if np.hypot(cx - hx, cy - hy) > 0.06 * ro:
        flags.append("hole eccentric")

    yy, xx = np.mgrid[:H, :W]
    r = np.hypot(xx - cx, yy - cy)
    rhole = np.hypot(xx - hx, yy - hy)
    r_in_lim = ro - p.outer_margin_um / upx
    ring = (r < r_in_lim) & (rhole > rh + p.inner_margin_um / upx)
    full_px = np.pi * (r_in_lim ** 2 - (rh + p.inner_margin_um / upx) ** 2)
    cut = 1 - ring.sum() / full_px
    if cut > 0.01:
        flags.append(f"ring clipped ({cut*100:.0f} % outside image)")
    ring_eval = ring & ~excl
    if excl[ring].mean() > 0.02:
        flags.append(f"{excl[ring].mean()*100:.0f} % of ring covered by annotation")

    sig = p.smooth_sigma_um / upx
    gs_all = norm_blur(gray, ring, sig)

    # Naht / Sektoren
    if p.seam == "none":
        seam = None
        sectors = [np.ones_like(ring)]
        ann = ring
    else:
        if p.seam == "auto":
            seam = detect_seam(gs_all, ring_eval, geo, upx, p)
        else:
            x = cx - p.seam_prior_offset * ro
            seam = dict(x0=x, y0=0, x1=x, y1=H, status="default", strength=float("nan"))
        if seam["y1"] != seam["y0"]:
            sx = seam["x0"] + (yy - seam["y0"]) * (seam["x1"] - seam["x0"]) / (seam["y1"] - seam["y0"])
        else:
            sx = np.full_like(xx, seam["x0"], dtype=float)
        gap = p.seam_gap_um / upx
        L, R = xx < sx - gap, xx > sx + gap
        sectors = [L, R]
        ann = ring & (L | R)
        if "not detected" in seam["status"]:
            flags.append("seam not detected – using default position")

    ann_eval = ann & ~excl
    gs = norm_blur(gray, ann, sig)
    rel = np.zeros_like(gs)
    for S in sectors:
        sel = ann_eval & S
        if sel.sum():
            rel[S] = gs[S] / np.median(gs[sel])
    bg = norm_blur(gray, ann, p.local_bg_sigma_um / upx)
    loc = np.where(ann, gs / np.maximum(bg, 1), 0)

    # Textur
    _kw = odd(round(p.tex_sigma_um / upx))
    _m1 = cv2.boxFilter(gray.astype(np.float32), ddepth=-1, ksize=(_kw, _kw), normalize=True)
    _m2 = cv2.boxFilter((gray.astype(np.float32))**2, ddepth=-1, ksize=(_kw, _kw), normalize=True)
    tex = np.sqrt(np.maximum(_m2 - _m1**2, 0))
    _med_tex = float(np.median(tex[ann_eval])) if ann_eval.any() else 1.0
    tex_rel = np.where(ann_eval, tex / max(_med_tex, 1e-6), 1.0)

    v = rel[ann_eval]
    spread = float(1.4826 * np.median(np.abs(v - np.median(v))))
    if p.threshold_mode == "adaptive":
        T = float(np.clip(1 + p.k_sigma * spread, p.t_min, p.t_max))
        if T in (p.t_min, p.t_max):
            flags.append("adaptive threshold at limit")
    else:
        T = p.threshold

    rim = r >= r_in_lim - p.rim_band_um / upx
    k_open = np.ones((odd(p.open_um / upx),) * 2, np.uint8)
    k_close = np.ones((odd(p.close_um / upx),) * 2, np.uint8)
    min_px = p.min_area_um2 / upx ** 2

    def segment(t):
        smooth_worn = (tex_rel < p.tex_low_thr) & (rel > p.tex_min_rel) & ann_eval
        m = (((rel > t) | ((loc > p.local_contrast_thr) & (rel > 1.0) & rim) | smooth_worn) & ann_eval)
        m = m.astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k_open)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k_close)
        m &= ann_eval.astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(m)
        keep = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= min_px])
        return keep

    mask = segment(T)
    frac = mask.sum() / ann_eval.sum()
    sens = {f"frac_T{int(round(t*100))}": round(float(segment(t).sum() / ann_eval.sum()), 4)
            for t in p.sensitivity}

    # Method band: systematic uncertainty from parameter grid sweep
    _sens_result = None
    if sensitivity_grid is not None:
        from . import sensitivity as _sens_mod
        _best = sensitivity_best if sensitivity_best is not None else _sens_mod.DEFAULT_BEST
        _sens_result = _sens_mod.sweep(
            rel=rel, tex_rel=tex_rel, loc=loc, rim=rim, ann_eval=ann_eval,
            spread=spread, local_contrast_thr=p.local_contrast_thr,
            k_open=k_open, k_close=k_close, min_px=min_px,
            t_min=p.t_min, t_max=p.t_max,
            grid=sensitivity_grid, best=_best,
        )

    ring_area_nominal_mm2 = np.pi / 4 * (p.outer_diam_mm ** 2 - p.inner_diam_mm ** 2)
    ring_area_analyzed_mm2 = np.pi * ((r_in_lim * upx) ** 2 - ((rh + p.inner_margin_um / upx) * upx) ** 2) / 1e6
    bore_d_mm = 2 * ro * upx / 1000
    radial_out = float((mask & rim).sum() / max(mask.sum(), 1))

    _geo_p = round(force_N / nom_area, 2) if force_N and nom_area else None
    _res_p = (round(force_N / (float(frac) * nom_area), 2)
              if force_N and nom_area and frac > 0 else None)

    res = dict(
        file=path.name,
        test_id=parsed["test"],
        material=parsed["material"],
        plate_material=parsed.get("plate_material"),
        condition=parsed.get("condition"),
        temperature_C=parsed.get("temperature_C"),
        rotation_deg=parsed.get("rotation_deg"),
        geometry=parsed.get("geometry"),
        method_name=parsed.get("method_name"),
        force_N=force_N,
        sample_area_mm2=nom_area,
        ring_area_nominal_mm2=round(ring_area_nominal_mm2, 2),
        ring_area_analyzed_mm2=round(ring_area_analyzed_mm2, 2),
        bore_diameter_measured_mm=round(bore_d_mm, 3),
        header_cropped_px=top, um_per_px=round(upx, 3),
        scale_bar_px=bar_px,
        seam_status=(seam["status"] if seam else "off"),
        seam_x_px=(round((seam["x0"] + seam["x1"]) / 2, 1) if seam else None),
        seam_strength=(round(seam["strength"], 3) if seam and np.isfinite(seam["strength"]) else None),
        spread=round(spread, 4), threshold=round(T, 3),
        wear_fraction=round(float(frac), 4),
        wear_area_mm2=round(float(frac) * ring_area_analyzed_mm2, 3),
        geometric_contact_pressure_MPa=_geo_p,
        resulting_contact_pressure_MPa=_res_p,
        share_in_rim_band=round(radial_out, 3),
        **sens,
        wear_fraction_min=(round(_sens_result.min_frac, 4) if _sens_result else None),
        wear_fraction_max=(round(_sens_result.max_frac, 4) if _sens_result else None),
        method_band_pp=(round((_sens_result.max_frac - _sens_result.min_frac) * 100, 2)
                        if _sens_result else None),
        _fracs_grid=(_sens_result.fracs if _sens_result else None),
        flags="; ".join(flags),
    )

    # Overlay
    outdir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    ov = rgb.copy()
    ov[mask] = (0.45 * ov[mask] + 0.55 * np.array([230, 0, 0])).astype(np.uint8)
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(ov, cnts, -1, (255, 0, 0), 1)
    cv2.circle(ov, (int(round(cx)), int(round(cy))), int(round(ro)), (0, 170, 255), 1)
    cv2.circle(ov, (int(round(hx)), int(round(hy))), int(round(rh)), (0, 170, 255), 1)
    if seam:
        p0 = (int(seam["x0"] + (cy - ro - seam["y0"]) * (seam["x1"] - seam["x0"]) / max(seam["y1"] - seam["y0"], 1e-6)), int(cy - ro))
        p1 = (int(seam["x0"] + (cy + ro - seam["y0"]) * (seam["x1"] - seam["x0"]) / max(seam["y1"] - seam["y0"], 1e-6)), int(cy + ro))
        cv2.line(ov, p0, p1, (255, 255, 0), 1, cv2.LINE_AA)
    scale = max(1, int(np.ceil(1100 / W)))
    im = Image.fromarray(ov).resize((W * scale, H * scale), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    txt = f"{stem}: {frac*100:.1f} % der Ringfläche (T = +{(T-1)*100:.0f} %)"
    if p.nominal_area_mm2:
        txt += f"  ≈ {frac*p.nominal_area_mm2:.2f} mm² (bei {p.nominal_area_mm2} mm²)".replace(".", ",")
    d.rectangle([8, 8, 18 + d.textlength(txt, font=font), 40], fill="white")
    d.text((13, 12), txt, fill="black", font=font)
    if flags:
        ft = "Hinweis: " + "; ".join(flags)
        d.rectangle([8, 44, 18 + d.textlength(ft, font=font), 76], fill=(255, 235, 150))
        d.text((13, 48), ft, fill="black", font=font)
    im.save(outdir / f"{stem}_overlay.png")

    if panel:
        tiles = []
        for t in p.sensitivity:
            m = segment(t)
            o = rgb.copy(); o[m] = (0.45 * o[m] + 0.55 * np.array([230, 0, 0])).astype(np.uint8)
            ti = Image.fromarray(o).resize((W * scale // 2, H * scale // 2), Image.LANCZOS)
            dd = ImageDraw.Draw(ti); s = f"+{(t-1)*100:.0f} %: {m.sum()/ann_eval.sum()*100:.1f} %"
            dd.rectangle([4, 4, 12 + dd.textlength(s, font=font), 34], fill="white"); dd.text((8, 8), s, fill="black", font=font)
            tiles.append(ti)
        tw, th = tiles[0].size
        pan = Image.new("RGB", (2 * tw + 10, 2 * th + 10), "white")
        for i, ti in enumerate(tiles[:4]):
            pan.paste(ti, ((i % 2) * (tw + 10), (i // 2) * (th + 10)))
        pan.save(outdir / f"{stem}_varianten.png")
    return res
