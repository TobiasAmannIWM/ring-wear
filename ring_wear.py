#!/usr/bin/env python3
"""
ring_wear.py – Automatische Abschätzung der hellen (verschlissenen) Fläche auf
Ring-Stirnflächen aus Lichtmikroskopbildern.

Verfahren (identisch zur manuellen Auswertung, alle Längen in µm):
  1. Bild laden, einfarbigen Kopfbereich abschneiden, rote/blaue Markierungen
     entfernen (Inpainting) und von der Auswertung ausschließen.
  2. Maßstabsbalken unten rechts finden  -> µm/px  (Balkenlänge per --bar-um).
  3. Ringgeometrie: Bohrung = größter dunkler, runder Fleck nahe der Bildmitte;
     Bohrungskante (max. Helligkeitsanstieg) und äußere dunkle Nut (radiales
     Minimum) werden über 360° abgetastet und robust als Kreise gefittet.
  4. Trennlinie der Schleifrichtung ("Naht", ca. 0,26·r_außen links der Mitte):
     Helligkeitssprung hell->dunkel oberhalb und unterhalb der Bohrung.
     Die Helligkeit wird je Ringhälfte auf den Median normiert, weil die
     Riefenorientierung die Reflexion stark ändert (kein Verschleiß!).
  5. Segmentierung: rel. Helligkeit > T  ODER  (lokaler Kontrast > 1,15 im
     äußeren 200-µm-Randband). T ist standardmäßig kontrastadaptiv:
     T = 1 + k·σ_rob (σ_rob = 1,4826·MAD der rel. Helligkeit, k = 1,38,
     kalibriert an Ring 1/2 mit T = +20 %). Alternativ feste Schwelle.
  6. Morphologische Bereinigung, Mindestfläche, Flächenanteil am Ring.

Ausgabe je Bild: Overlay-PNG (rot = als verschlissen klassifiziert),
optional Variantenpanel; gesamt: results.csv (+ params.json).

WICHTIGE EINSCHRÄNKUNGEN
  * "Hell" ≠ "verschlissen". Riefenrichtung, Beleuchtung, Fasen und
    Anlauffarben beeinflussen die Helligkeit. Ergebnis = Abschätzung.
  * Die adaptive Schwelle kompensiert Belichtungs-/Kontrastunterschiede,
    verkleinert aber Unterschiede zwischen Proben (stark verschlissene
    Proben streuen stärker -> höhere Schwelle). Bei identischen
    Aufnahmebedingungen ist --threshold-mode fixed vorzuziehen.
  * Die Spalten frac_T110 … frac_T125 zeigen die Schwellen-Sensitivität.
  * Bilder immer mit identischen Mikroskopeinstellungen aufnehmen
    (Belichtung, Beleuchtung, Vergrößerung, Bildgröße, ohne Markierungen).

Benutzung:
  python ring_wear.py bilder/*.png -o ergebnisse
  python ring_wear.py bilder/ -o ergebnisse --nominal-area 43.2 --panel
  python ring_wear.py bild.png --threshold-mode fixed --threshold 1.20
  python ring_wear.py bild.png --seam none          # ohne Hälften-Normierung
  python ring_wear.py bild.png --seam-offset 0.26   # Naht fest vorgeben

Abhängigkeiten: numpy, opencv-python, pillow
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, asdict, field
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
    # Lokale Grauwert-Standardabweichung über ein Fenster (~Rillenperiode):
    # Rillen → hohe Streuung; verschlissene/eingeglättete Fläche → niedrige Streuung.
    # Robuster gegenüber JPEG-Kompressionsartefakten als Sobel-Gradient.
    tex_sigma_um: float = 44.0    # Fenstergröße für lokale Std-Dev (~Rillenperiode, µm)
    tex_low_thr: float = 0.42     # Verschleiß wenn tex_rel < Schwelle (42 % des Ringmedians)
    tex_min_rel: float = 0.70     # Mindesthelligkeit (rel) für Texturbedingung

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
    """Extrahiert Versuchskennung, Material, Kraft und Fläche aus dem Dateinamen.

    Erwartet Muster T{N}_{Material}_{Force}N_{Area}mm2_ring,
    z. B. T10_INC718_810N_43mm2_ring.
    Gibt leere Strings / None zurück, wenn das Muster nicht passt.
    """
    base = {"test": "", "material": "", "force_N": None, "area_mm2": None}
    # Neues Schema: T{N}_{Material}_{Force}N_{Area}mm2_ring
    m = re.match(r"^(T\d+)_([A-Za-z0-9]+)_(\d+)N_(\d+)mm2_ring", stem, re.IGNORECASE)
    if m:
        return {**base, "test": m.group(1), "material": m.group(2),
                "force_N": float(m.group(3)), "area_mm2": float(m.group(4))}
    # Altes Schema (Rückwärtskompatibilität): ring{N}_{Material}_{TX}
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
    """Weißes Kästchen unten rechts, darin längster dunkler horizontaler Balken.
    Arbeitet auf dem Originalbild (farbige Markierungen zählen nicht als dunkel).
    Rückgabe: (Balkenlänge_px, bbox) oder (None, None)."""
    gray = rgb.astype(float).mean(2)
    vmax = rgb.max(2)
    H, W = gray.shape
    y0, x0 = int(H * 0.75), int(W * 0.6)
    sub = gray[y0:, x0:]
    wl = np.percentile(sub, 99.5)                # Weißwert (belichtungsunabhängig)
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
        # längste zusammenhängende Strecke
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
    # --- Bohrung: dunkler, kompakter Fleck nahe Bildmitte
    thr = min(55.0, np.percentile(g, 10))
    dark = ((g < thr) & ~excl).astype(np.uint8)
    k = max(3, int(round(min(H, W) / 70)) | 1)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    # Löcher füllen (Bohrung ist innen nicht überall gleich dunkel)
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
        fill = a / (w * h)                       # Kreis: ~0,785
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
        X, Y = [], []
        for th in np.linspace(0, 2 * np.pi, 360, endpoint=False):
            R = np.arange(lo, hi, 0.5)
            xs, ys = cx + R * np.cos(th), cy + R * np.sin(th)
            if (xs < 1).any() or (xs > W - 2).any() or (ys < 1).any() or (ys > H - 2).any():
                continue
            xi, yi = xs.astype(int), ys.astype(int)
            if excl[yi, xi].mean() > 0.5:   # überwiegend verdeckt -> auslassen
                continue
            v = g[yi, xi]
            i = np.argmin(v) if mode == "min" else np.argmax(np.diff(v))
            X.append(xs[i]); Y.append(ys[i])
        return np.array(X), np.array(Y)

    # --- Bohrungskante
    X, Y = scan(hx, hy, 0.75 * r_blob, 1.4 * r_blob, "grad")
    if len(X) < 60:
        raise RuntimeError("Bohrungskante nicht erfassbar")
    hole, hole_rms, _ = robust_circle(X, Y)
    # --- sichtbare Außengrenze im Bild (erster Helligkeits-Minimum im Scan-
    # bereich 2,3–3,3 × r_Bohrung). Der nominale Ring-Außenrand (OD=8mm)
    # liegt bei dieser Vergrößerung typischerweise außerhalb des Bildausschnitts.
    X, Y = scan(hole[0], hole[1], 2.3 * hole[2], 3.3 * hole[2], "min")
    if len(X) < 60:
        raise RuntimeError("Äußere Bildgrenze nicht erfassbar (Ring angeschnitten?)")
    outer, outer_rms, n_out = robust_circle(X, Y)
    return dict(hole=hole, outer=outer, hole_rms=hole_rms, outer_rms=outer_rms,
                outer_points=n_out)


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
        # Plausibilität: Naht annähernd senkrecht
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
def analyse(path: Path, p: Params, outdir: Path, panel=False, font=None):
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
    if bar_box is not None:   # Maßstabsbalken nie mitauswerten
        x, y, w, h = bar_box
        excl[max(0, y - 3):y + h + 3, max(0, x - 3):x + w + 3] = True

    geo = detect_geometry(gray, excl)
    cx, cy, ro = geo["outer"]
    hx, hy, rh = geo["hole"]
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

    # Textur: lokale Grauwert-Standardabweichung als Rillenpräsenz-Maß.
    # Schleifrillen erzeugen große Helligkeitsschwankungen im Fenster → hohe Std-Dev.
    # Verschlissene/eingeglättete Fläche: nur JPEG-Rauschen (1–5 Grauwerte) → sehr niedrige Std-Dev.
    # Viel besserer Kontrast als Sobel-Gradient (der durch JPEG-Block-Artefakte dominiert wird).
    _kw = odd(round(p.tex_sigma_um / upx))  # Fenstergröße passend zur Rillenperiode
    _m1 = cv2.boxFilter(gray.astype(np.float32), ddepth=-1, ksize=(_kw, _kw), normalize=True)
    _m2 = cv2.boxFilter((gray.astype(np.float32))**2, ddepth=-1, ksize=(_kw, _kw), normalize=True)
    tex = np.sqrt(np.maximum(_m2 - _m1**2, 0))  # lokale Standardabweichung der Grauwerte
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
        # Texturkriterium: niedrige lokale Std-Dev = Rillen verschwunden = eingeglättet = verschlissen
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

    # Flächen
    # Nominale Ringfläche aus Nennmaßen (Zeichnungsangabe, unabhängig vom Bild)
    ring_area_nominal_mm2 = np.pi / 4 * (p.outer_diam_mm ** 2 - p.inner_diam_mm ** 2)
    # Im Bild ausgewertete Fläche (zwischen sichtbarer Bohrungskante und Außengrenze)
    ring_area_analyzed_mm2 = np.pi * ((r_in_lim * upx) ** 2 - ((rh + p.inner_margin_um / upx) * upx) ** 2) / 1e6
    bore_d_mm = 2 * ro * upx / 1000   # detektierte sichtbare Außengrenze (≈ Bohrungsrand)
    radial_out = float((mask & rim).sum() / max(mask.sum(), 1))

    # Kontaktdrücke aus Dateiname (None wenn Namensschema nicht passt)
    _geo_p = round(force_N / nom_area, 2) if force_N and nom_area else None
    _res_p = (round(force_N / (float(frac) * nom_area), 2)
              if force_N and nom_area and frac > 0 else None)

    res = dict(
        file=path.name,
        test_id=parsed["test"],
        material=parsed["material"],
        force_N=force_N,
        sample_area_mm2=nom_area,
        ring_area_nominal_mm2=round(ring_area_nominal_mm2, 2),   # aus OD/ID-Nennmaß
        ring_area_analyzed_mm2=round(ring_area_analyzed_mm2, 2), # nach Randabzug
        bore_diameter_measured_mm=round(bore_d_mm, 3),           # Bildmessung Bohrung
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
        flags="; ".join(flags),
    )

    # Overlay
    outdir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    ov = rgb.copy()
    ov[mask] = (0.45 * ov[mask] + 0.55 * np.array([230, 0, 0])).astype(np.uint8)
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(ov, cnts, -1, (255, 0, 0), 1)
    # Detected boundaries drawn at the black ring edges (no margin offset)
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


# --------------------------------------------------------------------------- #
# Excel-Ausgabe
# --------------------------------------------------------------------------- #
def write_excel(rows: list, outdir: Path) -> Path | None:
    """Schreibt results.xlsx mit den wichtigsten Ergebnisspalten auf Englisch."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl not installed – Excel output skipped (pip install openpyxl)")
        return None

    wb = Workbook()
    ws = wb.active
    ws.title = "Wear results"

    headers = [
        "File", "Test", "Material",
        "Force (N)",
        "Sample area - filename (mm²)", "Ring area - nominal OD/ID (mm²)", "Ring area - analyzed (mm²)",
        "Bore diameter - measured (mm)",
        "Wear fraction (%)", "Wear area (mm²)",
        "Geometric contact pressure (MPa)", "Resulting contact pressure (MPa)",
        "µm/px", "Threshold", "Seam status", "Flags",
    ]
    hfill = PatternFill("solid", fgColor="1F4E79")
    hfont = Font(bold=True, color="FFFFFF")
    for col, h in enumerate(headers, 1):
        c = ws.cell(1, col, h)
        c.fill = hfill
        c.font = hfont
        c.alignment = Alignment(horizontal="center")

    for row in rows:
        frac = row.get("wear_fraction")
        ws.append([
            row.get("file", ""),
            row.get("test_id", ""),
            row.get("material", ""),
            row.get("force_N", ""),
            row.get("sample_area_mm2", ""),
            row.get("ring_area_nominal_mm2", ""),
            row.get("ring_area_analyzed_mm2", ""),
            row.get("bore_diameter_measured_mm", ""),
            round(frac * 100, 2) if isinstance(frac, (int, float)) else "",
            row.get("wear_area_mm2", ""),
            row.get("geometric_contact_pressure_MPa", ""),
            row.get("resulting_contact_pressure_MPa", ""),
            row.get("um_per_px", ""),
            row.get("threshold", ""),
            row.get("seam_status", ""),
            row.get("flags", ""),
        ])

    # Spaltenbreite automatisch anpassen
    for col in ws.columns:
        width = max((len(str(c.value or "")) for c in col), default=8) + 2
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(width, 50)

    # Kopfzeile einfrieren
    ws.freeze_panes = "A2"

    path = outdir / "results.xlsx"
    wb.save(path)
    return path


# --------------------------------------------------------------------------- #
# Statistics helpers
# --------------------------------------------------------------------------- #
def _group_stats(rows):
    """Group rows by (force_N, material) and return mean ± std for each group.

    Returns dict:
        (force_N, material) → {
            'wear_area':  (mean_mm2, std_mm2, n),
            'resulting_p': (mean_MPa, std_MPa, n) or None,
        }
    """
    import statistics as _st
    from collections import defaultdict
    groups: dict = defaultdict(lambda: {"wa": [], "rp": []})
    for row in rows:
        frac     = row.get("wear_fraction")
        force    = row.get("force_N")
        mat      = row.get("material")
        nom_area = row.get("ring_area_nominal_mm2")
        res_p    = row.get("resulting_contact_pressure_MPa")
        if not isinstance(frac, float) or force is None or not mat or not nom_area:
            continue
        groups[(float(force), mat)]["wa"].append(frac * nom_area)
        if isinstance(res_p, float):
            groups[(float(force), mat)]["rp"].append(res_p)
    result = {}
    for key, data in groups.items():
        wa = data["wa"]
        rp = data["rp"]
        result[key] = {
            "wear_area":   (sum(wa)/len(wa),
                            _st.stdev(wa) if len(wa) >= 2 else 0.0,
                            len(wa)),
            "resulting_p": (sum(rp)/len(rp),
                            _st.stdev(rp) if len(rp) >= 2 else 0.0,
                            len(rp)) if rp else None,
        }
    return result


def _regression_through_origin(pts_xy):
    """Least-squares regression y = k·x forced through origin.

    Returns (k, r2) where r² = 1 − Σresid² / Σy².
    Returns (None, None) if fewer than 2 points.
    """
    xs = [p[0] for p in pts_xy]
    ys = [p[1] for p in pts_xy]
    if len(xs) < 2:
        return None, None
    sx2 = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    k   = sxy / sx2 if sx2 else 0.0
    ss_res = sum((y - k * x) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum(y * y for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return k, r2


def _find_new_probe(material: str, neu_dir: "Path | None") -> "Path | None":
    """Return path to a new/unworn probe image for *material*, or None."""
    if neu_dir is None or not neu_dir.is_dir():
        return None
    IMG_EXT_SET = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    # 1. Try subdirectory named after material (case-insensitive)
    for sub in neu_dir.iterdir():
        if sub.is_dir() and sub.name.lower() == material.lower():
            for f in sorted(sub.iterdir()):
                if f.suffix.lower() in IMG_EXT_SET:
                    return f
    # 2. Fall back: any file in neu_dir whose name contains the material string
    for f in sorted(neu_dir.iterdir()):
        if f.suffix.lower() in IMG_EXT_SET and material.lower() in f.stem.lower():
            return f
    return None


def _copy_image_to_outdir(src: "Path", outdir: "Path", dest_name: str) -> "Path | None":
    """Copy *src* to *outdir/dest_name*; return dest path, or None on failure."""
    import shutil
    if src is None or not src.exists():
        return None
    dest = outdir / dest_name
    if not dest.exists():
        shutil.copy2(src, dest)
    return dest


# --------------------------------------------------------------------------- #
# Bar-chart helpers (grouped by material × normal force)
# --------------------------------------------------------------------------- #
def _bar_chart_data(rows):
    """Return (categories, series_dict) for a grouped bar chart with std.

    categories  : sorted list of force labels, e.g. ['810 N', '1620 N', ...]
    series_dict : {material: [(mean_mm2, std_mm2, n) | None, ...]} per category
    Wear area = wear_fraction × ring_area_nominal_mm2 (43.2 mm²).
    """
    stats = _group_stats(rows)
    if not stats:
        return [], {}
    forces    = sorted({f for f, _ in stats})
    materials = sorted({m for _, m in stats})
    categories = [f"{int(f) if f == int(f) else f} N" for f in forces]
    series_dict = {
        m: [stats.get((f, m), {}).get("wear_area") for f in forces]
        for m in materials
    }
    return categories, series_dict


def _bar_chart_svg(rows):
    """Grouped bar chart with mean bars and ±std error bars (HTML SVG)."""
    categories, series_dict = _bar_chart_data(rows)
    if not categories or not series_dict:
        return ""

    # Collect all mean values to scale y-axis
    all_means = [tup[0] for vals in series_dict.values() for tup in vals if tup is not None]
    all_stds  = [tup[1] for vals in series_dict.values() for tup in vals if tup is not None]
    if not all_means:
        return ""

    W, H = 820, 440
    PAD_L, PAD_R, PAD_T, PAD_B = 72, 170, 55, 68
    PW = W - PAD_L - PAD_R
    PH = H - PAD_T - PAD_B

    max_val = max(m + s for m, s in zip(all_means, all_stds)) * 1.25

    n_cats = len(categories)
    n_ser  = len(series_dict)
    group_w = PW / n_cats
    bar_gap = 0.08 * group_w
    bar_w   = max(6.0, (group_w - (n_ser + 1) * bar_gap) / n_ser)

    COLORS   = {"INC718": "#0072B2", "INC625M": "#E69F00"}
    FALLBACK = ["#56B4E9", "#009E73", "#CC79A7", "#D55E00"]
    mats     = list(series_dict.keys())
    colors   = [COLORS.get(m, FALLBACK[i % len(FALLBACK)]) for i, m in enumerate(mats)]

    def ypx(v):
        return PAD_T + PH - (v / max_val) * PH

    ticks = [max_val * i / 5 for i in range(6)]

    p = []
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'style="max-width:100%;height:auto;font-family:Arial,sans-serif;'
        f'background:#fff;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.12)">'
    )

    p.append(f'<text x="{W//2}" y="32" text-anchor="middle" font-size="14" '
             f'font-weight="bold" fill="#1f4e79">'
             f'Resulting Wear Area by Material and Normal Force</text>')
    p.append(f'<text x="{W//2}" y="49" text-anchor="middle" font-size="10" fill="#888">'
             f'Error bars: ±1 std dev across repeated experiments</text>')

    yl_x, yl_y = 14, PAD_T + PH // 2
    p.append(f'<text x="{yl_x}" y="{yl_y}" text-anchor="middle" font-size="11" '
             f'fill="#555" transform="rotate(-90 {yl_x} {yl_y})">Wear area (mm²)</text>')
    p.append(f'<text x="{PAD_L + PW//2}" y="{H - 6}" text-anchor="middle" '
             f'font-size="11" fill="#555">Normal force (N)</text>')

    for tv in ticks:
        yp = ypx(tv)
        p.append(f'<line x1="{PAD_L}" y1="{yp:.1f}" '
                 f'x2="{PAD_L + PW}" y2="{yp:.1f}" stroke="#ececec" stroke-width="1"/>')
        lbl = f"{tv:.2f}".rstrip("0").rstrip(".")
        p.append(f'<text x="{PAD_L - 6}" y="{yp + 4:.1f}" '
                 f'text-anchor="end" font-size="10" fill="#666">{lbl}</text>')

    p.append(f'<line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{PAD_T+PH}" '
             f'stroke="#aaa" stroke-width="1.5"/>')
    p.append(f'<line x1="{PAD_L}" y1="{PAD_T+PH}" '
             f'x2="{PAD_L+PW}" y2="{PAD_T+PH}" stroke="#aaa" stroke-width="1.5"/>')

    for ci, cat in enumerate(categories):
        gx = PAD_L + ci * group_w
        total_bw = n_ser * bar_w + (n_ser - 1) * bar_gap
        bar_start = gx + (group_w - total_bw) / 2

        p.append(f'<text x="{gx + group_w/2:.1f}" y="{PAD_T+PH+18}" '
                 f'text-anchor="middle" font-size="11" fill="#444">{cat}</text>')

        for si, (mat, vals) in enumerate(series_dict.items()):
            tup = vals[ci]
            if tup is None:
                continue
            mean_v, std_v, n_v = tup
            bx    = bar_start + si * (bar_w + bar_gap)
            bcx   = bx + bar_w / 2   # bar center x
            by    = ypx(mean_v)
            bh    = PAD_T + PH - by
            col   = colors[si]

            # Bar
            p.append(f'<rect x="{bx:.1f}" y="{by:.1f}" '
                     f'width="{bar_w:.1f}" height="{bh:.1f}" '
                     f'fill="{col}" opacity="0.9" rx="2"/>')

            # Value label
            if bh > 14:
                lbl = f"{mean_v:.2f}" if n_v < 2 else f"{mean_v:.2f}±{std_v:.2f}"
                p.append(f'<text x="{bcx:.1f}" y="{by - 5:.1f}" '
                         f'text-anchor="middle" font-size="9" '
                         f'fill="{col}" font-weight="bold">{lbl}</text>')

            # Error bar (only when n ≥ 2 and std > 0)
            if n_v >= 2 and std_v > 0:
                y_top = ypx(min(mean_v + std_v, max_val))
                y_bot = min(ypx(max(mean_v - std_v, 0.0)), PAD_T + PH)
                cap   = bar_w * 0.3
                p.append(f'<line x1="{bcx:.1f}" y1="{y_top:.1f}" '
                         f'x2="{bcx:.1f}" y2="{y_bot:.1f}" '
                         f'stroke="#333" stroke-width="1.5"/>')
                p.append(f'<line x1="{bcx - cap:.1f}" y1="{y_top:.1f}" '
                         f'x2="{bcx + cap:.1f}" y2="{y_top:.1f}" '
                         f'stroke="#333" stroke-width="1.5"/>')
                p.append(f'<line x1="{bcx - cap:.1f}" y1="{y_bot:.1f}" '
                         f'x2="{bcx + cap:.1f}" y2="{y_bot:.1f}" '
                         f'stroke="#333" stroke-width="1.5"/>')
                # n label below bar
                p.append(f'<text x="{bcx:.1f}" y="{PAD_T+PH+32}" '
                         f'text-anchor="middle" font-size="9" fill="#888">n={n_v}</text>')

    lx, ly = PAD_L + PW + 20, PAD_T + 10
    for si, mat in enumerate(mats):
        yl = ly + si * 24
        p.append(f'<rect x="{lx}" y="{yl}" width="16" height="16" '
                 f'fill="{colors[si]}" rx="3"/>')
        p.append(f'<text x="{lx + 22}" y="{yl + 12}" '
                 f'font-size="12" fill="#333">{mat}</text>')

    p.append('</svg>')
    return "\n".join(p)


def _scatter_svg(rows):
    """Scatter plot with regression through origin, error bars, and formula.

    Individual experiment points + grouped mean ± std error bars (when n ≥ 2).
    Dashed regression line p = k·F (through origin) per material.
    """
    pts = []
    for row in rows:
        force = row.get("force_N")
        rp    = row.get("resulting_contact_pressure_MPa")
        mat   = row.get("material")
        tid   = row.get("test_id", "")
        if isinstance(force, float) and isinstance(rp, float) and mat:
            pts.append((force, rp, mat, tid))
    if not pts:
        return ""

    # Grouped stats for error bars
    stats = _group_stats(rows)

    W, H = 820, 460
    PAD_L, PAD_R, PAD_T, PAD_B = 72, 180, 55, 68
    PW = W - PAD_L - PAD_R
    PH = H - PAD_T - PAD_B

    x_max = max(pt[0] for pt in pts) * 1.15
    y_max = max(pt[1] for pt in pts) * 1.25

    COLORS   = {"INC718": "#0072B2", "INC625M": "#E69F00"}
    FALLBACK = ["#56B4E9", "#009E73", "#CC79A7"]
    mats     = sorted({pt[2] for pt in pts})
    colors   = {m: COLORS.get(m, FALLBACK[i % len(FALLBACK)]) for i, m in enumerate(mats)}

    def xpx(v):
        return PAD_L + v / x_max * PW

    def ypx(v):
        return PAD_T + PH - v / y_max * PH

    x_ticks = [x_max * i / 5 for i in range(6)]
    y_ticks = [y_max * i / 5 for i in range(6)]

    # Compute regressions per material
    reg = {}
    for mat in mats:
        mat_pts = [(f, rp) for f, rp, m, _ in pts if m == mat]
        k, r2 = _regression_through_origin(mat_pts)
        if k is not None:
            reg[mat] = (k, r2)

    p = []
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'style="max-width:100%;height:auto;font-family:Arial,sans-serif;'
        f'background:#fff;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.12)">'
    )

    p.append(
        f'<text x="{W//2}" y="32" text-anchor="middle" font-size="14" '
        f'font-weight="bold" fill="#1f4e79">'
        f'Resulting Contact Pressure vs. Normal Force</text>'
    )
    p.append(
        f'<text x="{W//2}" y="49" text-anchor="middle" font-size="10" fill="#888">'
        f'Dashed lines: regression through origin  ·  Error bars: ±1 std dev</text>'
    )

    yl_x, yl_y = 14, PAD_T + PH // 2
    p.append(
        f'<text x="{yl_x}" y="{yl_y}" text-anchor="middle" font-size="11" fill="#555" '
        f'transform="rotate(-90 {yl_x} {yl_y})">'
        f'Resulting contact pressure (MPa)</text>'
    )
    p.append(
        f'<text x="{PAD_L + PW//2}" y="{H - 6}" text-anchor="middle" '
        f'font-size="11" fill="#555">Normal force (N)</text>'
    )

    for tv in x_ticks:
        xp = xpx(tv)
        p.append(f'<line x1="{xp:.1f}" y1="{PAD_T}" '
                 f'x2="{xp:.1f}" y2="{PAD_T+PH}" stroke="#ececec" stroke-width="1"/>')
        lbl = str(int(tv)) if tv == int(tv) else f"{tv:.0f}"
        p.append(f'<text x="{xp:.1f}" y="{PAD_T+PH+16}" '
                 f'text-anchor="middle" font-size="10" fill="#666">{lbl}</text>')

    for tv in y_ticks:
        yp = ypx(tv)
        p.append(f'<line x1="{PAD_L}" y1="{yp:.1f}" '
                 f'x2="{PAD_L+PW}" y2="{yp:.1f}" stroke="#ececec" stroke-width="1"/>')
        lbl = f"{tv:.0f}" if tv >= 10 else f"{tv:.1f}"
        p.append(f'<text x="{PAD_L-6}" y="{yp+4:.1f}" '
                 f'text-anchor="end" font-size="10" fill="#666">{lbl}</text>')

    p.append(f'<line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{PAD_T+PH}" '
             f'stroke="#aaa" stroke-width="1.5"/>')
    p.append(f'<line x1="{PAD_L}" y1="{PAD_T+PH}" '
             f'x2="{PAD_L+PW}" y2="{PAD_T+PH}" stroke="#aaa" stroke-width="1.5"/>')

    # Regression lines (dashed, behind points)
    for mat in mats:
        if mat not in reg:
            continue
        k, r2 = reg[mat]
        col = colors.get(mat, "#888")
        x0, x1_v = 0.0, x_max
        y0_v = k * x0
        y1_v = k * x1_v
        # clip to plot area
        if y1_v > y_max:
            x1_v = y_max / k
            y1_v = y_max
        rxp0, ryp0 = xpx(x0), ypx(y0_v)
        rxp1, ryp1 = xpx(x1_v), ypx(y1_v)
        p.append(
            f'<line x1="{rxp0:.1f}" y1="{PAD_T+PH:.1f}" '   # from origin on x-axis
            f'x2="{rxp1:.1f}" y2="{ryp1:.1f}" '
            f'stroke="{col}" stroke-width="1.8" stroke-dasharray="6,4" opacity="0.7"/>'
        )

    # Error bars for grouped experiments (mean ± std, only when n ≥ 2)
    for (force, mat), gdata in stats.items():
        rp_data = gdata.get("resulting_p")
        if rp_data is None:
            continue
        mean_rp, std_rp, n_rp = rp_data
        if n_rp < 2 or std_rp <= 0:
            continue
        col  = colors.get(mat, "#888")
        xc   = xpx(force)
        yc   = ypx(mean_rp)
        y_hi = ypx(min(mean_rp + std_rp, y_max))
        y_lo = min(ypx(max(mean_rp - std_rp, 0.0)), PAD_T + PH)
        cap  = 5
        p.append(f'<line x1="{xc:.1f}" y1="{y_hi:.1f}" x2="{xc:.1f}" y2="{y_lo:.1f}" '
                 f'stroke="{col}" stroke-width="2"/>')
        p.append(f'<line x1="{xc-cap:.1f}" y1="{y_hi:.1f}" x2="{xc+cap:.1f}" y2="{y_hi:.1f}" '
                 f'stroke="{col}" stroke-width="2"/>')
        p.append(f'<line x1="{xc-cap:.1f}" y1="{y_lo:.1f}" x2="{xc+cap:.1f}" y2="{y_lo:.1f}" '
                 f'stroke="{col}" stroke-width="2"/>')

    # Individual points
    R = 6
    for force, rp, mat, tid in pts:
        col = colors.get(mat, "#888")
        xc, yc = xpx(force), ypx(rp)
        p.append(
            f'<circle cx="{xc:.1f}" cy="{yc:.1f}" r="{R}" '
            f'fill="{col}" opacity="0.85" stroke="white" stroke-width="1.5"/>'
        )

    # Point labels
    for force, rp, mat, tid in pts:
        col = colors.get(mat, "#888")
        xc, yc = xpx(force), ypx(rp)
        if tid:
            lx_lbl = xc + R + 4 if xc < PAD_L + PW * 0.85 else xc - R - 4
            anchor = "start" if xc < PAD_L + PW * 0.85 else "end"
            p.append(
                f'<text x="{lx_lbl:.1f}" y="{yc + 4:.1f}" '
                f'font-size="10" fill="{col}" text-anchor="{anchor}">{tid}</text>'
            )

    # Legend + regression formulas
    lx, ly = PAD_L + PW + 20, PAD_T + 10
    for i, mat in enumerate(mats):
        yl  = ly + i * 56
        col = colors[mat]
        p.append(f'<circle cx="{lx+8}" cy="{yl+8}" r="7" '
                 f'fill="{col}" opacity="0.85"/>')
        p.append(f'<text x="{lx+22}" y="{yl+12}" font-size="12" '
                 f'font-weight="bold" fill="#333">{mat}</text>')
        if mat in reg:
            k, r2 = reg[mat]
            p.append(f'<text x="{lx+4}" y="{yl+28}" font-size="10" fill="{col}">'
                     f'p = {k:.4f}·F</text>')
            p.append(f'<text x="{lx+4}" y="{yl+42}" font-size="10" fill="#888">'
                     f'R² = {r2:.4f}</text>')

    p.append('</svg>')
    return "\n".join(p)


# --------------------------------------------------------------------------- #
# HTML report (stdlib only – no extra dependencies)
# --------------------------------------------------------------------------- #
def write_html(rows: list, outdir: Path) -> Path:
    """Single-file HTML report; overlay images loaded via relative path."""
    import datetime
    import html as _html

    def esc(v):
        return _html.escape(str(v)) if v is not None else "–"

    def wear_cls(frac):
        if isinstance(frac, float):
            if frac > 0.15: return "wear-high"
            if frac > 0.07: return "wear-mid"
            return "wear-low"
        return ""

    valid = sorted(
        [r for r in rows if isinstance(r.get("wear_fraction"), float)],
        key=lambda r: r["wear_fraction"], reverse=True,
    )
    n_ok = len(valid)
    date_str = datetime.date.today().isoformat()

    # --- summary table rows ---
    sum_rows = []
    for rank, row in enumerate(valid, 1):
        frac   = row["wear_fraction"]
        cls    = wear_cls(frac)
        geo_p  = row.get("geometric_contact_pressure_MPa")
        res_p  = row.get("resulting_contact_pressure_MPa")
        wear_a = row.get("wear_area_mm2")
        flags  = esc(row.get("flags") or "")
        flag_td = f'<span class="flag-warn">{flags}</span>' if flags and flags != "–" else "–"
        sum_rows.append(
            f"<tr>"
            f"<td>{rank}</td>"
            f"<td>{esc(row.get('test_id'))}</td>"
            f"<td>{esc(row.get('material'))}</td>"
            f"<td>{esc(row.get('force_N'))}</td>"
            f"<td class='{cls}'><b>{frac*100:.1f}</b></td>"
            f"<td>{f'{wear_a:.3f}' if wear_a else '–'}</td>"
            f"<td>{f'{geo_p:.1f}' if geo_p else '–'}</td>"
            f"<td>{f'{res_p:.1f}' if res_p else '–'}</td>"
            f"<td>{flag_td}</td>"
            f"</tr>"
        )
    for row in rows:
        if not isinstance(row.get("wear_fraction"), float):
            sum_rows.append(
                f"<tr>"
                f"<td>–</td>"
                f"<td colspan='7' style='color:#888'>{esc(row.get('file','?'))}</td>"
                f"<td class='flag-warn'>{esc(row.get('flags','ERROR'))}</td>"
                f"</tr>"
            )

    # --- detail cards ---
    cards = []
    for row in rows:
        if not isinstance(row.get("wear_fraction"), float):
            continue
        stem       = Path(row.get("file", "")).stem
        # 3 images: new probe, worn original, wear overlay
        new_path   = row.get("_new_probe_outdir")   # filename only (already copied to outdir)
        worn_path  = row.get("_worn_outdir")         # filename only (already copied to outdir)
        ov_file    = f"{stem}_overlay.png"
        def _img(fname, alt, caption):
            exists = fname and (outdir / fname).exists()
            tag = (f'<img src="{esc(fname)}" alt="{esc(alt)}">'
                   if exists else f'<div class="img-missing">{esc(alt)}<br>not found</div>')
            return (f'<div class="img-cell">{tag}'
                    f'<div class="img-caption">{caption}</div></div>')
        img_block = (
            f'<div class="img-row">'
            f'{_img(worn_path,  "worn probe", "② Worn probe")}'
            f'{_img(new_path,   "new probe",  "① New probe (unworn)")}'
            f'{_img(ov_file,    "wear overlay", "③ Wear detected (red)")}'
            f'</div>'
        )
        frac   = row.get("wear_fraction", 0.0)
        cls    = wear_cls(frac)
        geo_p  = row.get("geometric_contact_pressure_MPa")
        res_p  = row.get("resulting_contact_pressure_MPa")
        wear_a = row.get("wear_area_mm2")
        flags  = row.get("flags", "") or ""
        flag_val = f'<span class="flag-warn">{esc(flags)}</span>' if flags else "–"
        metrics = [
            ("Wear fraction",         f'<span class="{cls}"><b>{frac*100:.1f} %</b></span>'),
            ("Wear area (analyzed)",  f"{wear_a:.3f} mm²" if wear_a else "–"),
            ("Ring area nominal",     f"{esc(row.get('ring_area_nominal_mm2'))} mm²"),
            ("Ring area analyzed",    f"{esc(row.get('ring_area_analyzed_mm2'))} mm²"),
            ("Bore Ø measured",       f"{esc(row.get('bore_diameter_measured_mm'))} mm"),
            ("Geometric pressure",    f"{geo_p:.1f} MPa"  if geo_p else "–"),
            ("Resulting pressure",    f"{res_p:.1f} MPa"  if res_p else "–"),
            ("µm/px",                 esc(row.get("um_per_px"))),
            ("Threshold",             esc(row.get("threshold"))),
            ("Seam",                  esc(row.get("seam_status"))),
            ("Flags",                 flag_val),
        ]
        mrows = "".join(f"<tr><td>{label}</td><td>{val}</td></tr>" for label, val in metrics)
        title = (f"{esc(row.get('test_id','?'))}"
                 f"&ensp;–&ensp;{esc(row.get('material','?'))}"
                 f"&ensp;·&ensp;{esc(row.get('force_N','?'))} N")
        cards.append(
            f'<div class="card"><h3>{title}</h3>'
            f'{img_block}'
            f'<table class="metrics"><tbody>{mrows}</tbody></table>'
            f'</div>'
        )

    css = (
        "body{font-family:Arial,sans-serif;margin:0;padding:24px 36px;"
        "background:#f4f6f8;color:#222}"
        "h1{color:#1f4e79;border-bottom:3px solid #1f4e79;padding-bottom:8px;margin-top:0}"
        "h2{color:#1f4e79;margin-top:36px}"
        "h3{color:#2c5e8e;margin:0 0 12px;font-size:1.05em}"
        ".meta{color:#666;font-size:.9em;margin-bottom:24px}"
        "table.summary{border-collapse:collapse;width:100%;background:#fff;"
        "box-shadow:0 1px 5px rgba(0,0,0,.12);border-radius:4px;overflow:hidden}"
        "table.summary th{background:#1f4e79;color:#fff;padding:8px 12px;"
        "text-align:left;font-size:.83em;white-space:nowrap}"
        "table.summary td{padding:7px 12px;border-bottom:1px solid #e0e0e0;font-size:.83em}"
        "table.summary tr:last-child td{border-bottom:none}"
        "table.summary tr:nth-child(even) td{background:#e8f2fb}"
        "table.summary tr:hover td{background:#cce0f5}"
        ".wear-high{color:#a00}"
        ".wear-mid{color:#a35200}"
        ".wear-low{color:#055}"
        ".flag-warn{color:#a35200;font-size:.85em}"
        ".card{background:#fff;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.12);"
        "margin-bottom:24px;padding:18px 22px}"
        ".img-row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}"
        ".img-cell{flex:1 1 28%;min-width:180px;text-align:center}"
        ".img-cell img{width:100%;height:auto;border:1px solid #ddd;border-radius:4px}"
        ".img-caption{font-size:.78em;color:#555;margin-top:4px;font-style:italic}"
        ".img-missing{background:#f0f0f0;border:1px dashed #bbb;border-radius:4px;"
        "padding:20px 8px;color:#999;font-size:.8em;min-height:80px;"
        "display:flex;align-items:center;justify-content:center;text-align:center}"
        "table.metrics{font-size:.84em;border-collapse:collapse}"
        "table.metrics td{padding:4px 10px 4px 0;vertical-align:top}"
        "table.metrics td:first-child{font-weight:bold;color:#555;"
        "white-space:nowrap;min-width:155px}"
    )

    chart_svg   = _bar_chart_svg(rows)
    scatter_svg = _scatter_svg(rows)
    chart_block = ""
    if chart_svg:
        chart_block += (
            "\n<h2>Wear Area by Material and Normal Force</h2>\n"
            "<p style=\"color:#666;font-size:.85em\">"
            "Wear area = wear fraction × nominal ring area (43.2 mm²). "
            "Multiple experiments per group are averaged.</p>\n"
            f"{chart_svg}\n"
        )
    if scatter_svg:
        chart_block += (
            "\n<h2>Resulting Contact Pressure vs. Normal Force</h2>\n"
            "<p style=\"color:#666;font-size:.85em\">"
            "Resulting contact pressure = normal force / "
            "(wear fraction × nominal ring area).</p>\n"
            f"{scatter_svg}\n"
        )

    content = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<title>Ring Wear Analysis Report</title>
<style>{css}</style>
</head>
<body>
<h1>Ring Wear Analysis Report</h1>
<p class="meta">Generated: {date_str} &nbsp;·&nbsp; {n_ok} of {len(rows)} images analysed</p>

<h2>Summary (sorted by wear fraction)</h2>
<table class="summary">
<thead><tr>
  <th>Rank</th><th>Test</th><th>Material</th><th>Force (N)</th>
  <th>Wear (%)</th><th>Wear area (mm²)</th>
  <th>Geometric p (MPa)</th><th>Resulting p (MPa)</th><th>Flags</th>
</tr></thead>
<tbody>{"".join(sum_rows)}</tbody>
</table>
{chart_block}
<h2>Details</h2>
{"".join(cards)}
</body></html>"""

    path = outdir / "results.html"
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# PPTX report
# --------------------------------------------------------------------------- #
def write_pptx(rows: list, outdir: Path) -> Path | None:
    """PowerPoint report: title slide + one slide per experiment + summary."""
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
    except ImportError:
        print("python-pptx not installed – PPTX output skipped  (pip install python-pptx)")
        return None

    import datetime

    PW, PH = Inches(13.33), Inches(7.5)
    prs = Presentation()
    prs.slide_width  = PW
    prs.slide_height = PH
    blank = prs.slide_layouts[6]  # fully blank

    def _txb(sl, left, top, w, h, text, *, bold=False, sz=13,
             color=(30, 30, 30), align=PP_ALIGN.LEFT):
        shp = sl.shapes.add_textbox(Inches(left), Inches(top),
                                    Inches(w), Inches(h))
        tf = shp.text_frame
        tf.word_wrap = True
        para = tf.paragraphs[0]
        para.alignment = align
        run = para.add_run()
        run.text = str(text)
        run.font.bold  = bold
        run.font.size  = Pt(sz)
        run.font.color.rgb = RGBColor(*color)

    def _bg(sl, r, g, b):
        fill = sl.background.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor(r, g, b)

    # ── Title slide ──────────────────────────────────────────────────────────
    sl = prs.slides.add_slide(blank)
    _bg(sl, 31, 78, 121)
    _txb(sl, 0.5, 2.0, 12.3, 1.3, "Ring Wear Analysis Report",
         bold=True, sz=38, color=(255, 255, 255), align=PP_ALIGN.CENTER)
    n_ok = sum(1 for r in rows if isinstance(r.get("wear_fraction"), float))
    sub  = (f"Generated {datetime.date.today().isoformat()}"
            f"  ·  {n_ok} of {len(rows)} images analysed")
    _txb(sl, 0.5, 3.5, 12.3, 0.7, sub, sz=18,
         color=(180, 215, 245), align=PP_ALIGN.CENTER)

    # ── Per-experiment slides ─────────────────────────────────────────────────
    for row in rows:
        if not isinstance(row.get("wear_fraction"), float):
            continue
        sl   = prs.slides.add_slide(blank)
        _bg(sl, 248, 248, 248)
        stem = Path(row.get("file", "unknown")).stem

        title = (f"{row.get('test_id','?')}  –  {row.get('material','?')}"
                 f"  ·  {row.get('force_N','?')} N")
        _txb(sl, 0.25, 0.08, 13.0, 0.55, title,
             bold=True, sz=20, color=(31, 78, 121))

        # Three images: worn original, new probe, wear overlay
        IMG_CAPTIONS = ["② Worn probe", "① New probe (unworn)", "③ Wear detected"]
        img_specs = [
            row.get("_worn_abspath"),                        # worn original
            row.get("_new_probe_abspath"),                   # new probe
            str(outdir / f"{stem}_overlay.png"),             # overlay
        ]
        IMG_Y, IMG_W, IMG_GAP = 0.72, 2.55, 0.12
        for idx, (img_abs, caption) in enumerate(zip(img_specs, IMG_CAPTIONS)):
            ix = 0.25 + idx * (IMG_W + IMG_GAP)
            if img_abs and Path(img_abs).exists():
                try:
                    sl.shapes.add_picture(str(img_abs), Inches(ix), Inches(IMG_Y),
                                          width=Inches(IMG_W))
                except Exception:
                    pass
            _txb(sl, ix, IMG_Y + 4.0, IMG_W, 0.3, caption,
                 sz=9, color=(100, 100, 100), align=PP_ALIGN.CENTER)

        frac   = row.get("wear_fraction", 0.0)
        geo_p  = row.get("geometric_contact_pressure_MPa")
        res_p  = row.get("resulting_contact_pressure_MPa")
        wear_a = row.get("wear_area_mm2")
        mx = 8.35   # left edge of metrics column
        lines = [
            ("Wear fraction",        f"{frac*100:.1f} %"),
            ("Wear area (analyzed)", f"{wear_a:.3f} mm²" if wear_a else "–"),
            ("Geometric pressure",   f"{geo_p:.1f} MPa"  if geo_p  else "–"),
            ("Resulting pressure",   f"{res_p:.1f} MPa"  if res_p  else "–"),
            ("Bore Ø measured",      f"{row.get('bore_diameter_measured_mm','–')} mm"),
            ("Ring area nominal",    f"{row.get('ring_area_nominal_mm2','–')} mm²"),
            ("Ring area analyzed",   f"{row.get('ring_area_analyzed_mm2','–')} mm²"),
            ("µm/px",                str(row.get("um_per_px", "–"))),
            ("Threshold",            str(row.get("threshold", "–"))),
            ("Seam",                 row.get("seam_status", "–")),
            ("Flags",                row.get("flags", "") or "–"),
        ]
        y = 0.72
        for label, value in lines:
            _txb(sl, mx,        y, 2.5, 0.37, label + ":",
                 bold=True, sz=11, color=(80, 80, 80))
            _txb(sl, mx + 2.55, y, 2.3, 0.37, value, sz=11)
            y += 0.37

    # ── Bar chart slide ───────────────────────────────────────────────────────
    _cats, _series = _bar_chart_data(rows)
    if _cats and _series:
        try:
            from pptx.chart.data import ChartData
            from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION

            sl = prs.slides.add_slide(blank)
            _bg(sl, 255, 255, 255)
            _txb(sl, 0.3, 0.08, 12.7, 0.6,
                 "Resulting Wear Area by Material and Normal Force",
                 bold=True, sz=24, color=(31, 78, 121))
            _txb(sl, 0.3, 0.62, 12.7, 0.3,
                 "Wear area = wear fraction × nominal ring area (43.2 mm²). "
                 "Multiple experiments per group are averaged.",
                 sz=10, color=(130, 130, 130))

            CHART_COLORS = {
                "INC718":  RGBColor(0,   114, 178),
                "INC625M": RGBColor(230, 159,   0),
            }
            FALLBACK_COL = [RGBColor(86, 180, 233), RGBColor(0, 158, 115)]

            cd = ChartData()
            cd.categories = _cats
            for mat, vals in _series.items():
                # vals are (mean, std, n) tuples; PPTX chart needs plain floats
                cd.add_series(mat, [v[0] if v is not None else None for v in vals])

            chart_shp = sl.shapes.add_chart(
                XL_CHART_TYPE.COLUMN_CLUSTERED,
                Inches(0.4), Inches(1.0),
                Inches(12.5), Inches(6.2),
                cd,
            )
            chart = chart_shp.chart
            chart.has_title   = False
            chart.has_legend  = True
            chart.legend.position         = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False

            # Y-axis: start at 0, label
            va = chart.value_axis
            va.minimum_scale = 0
            va.has_title = True
            va.axis_title.text_frame.text = "Wear area (mm²)"

            # X-axis label
            ca = chart.category_axis
            ca.has_title = True
            ca.axis_title.text_frame.text = "Normal force (N)"

            # Series colors
            for i, mat in enumerate(list(_series.keys())):
                s = chart.series[i]
                s.format.fill.solid()
                s.format.fill.fore_color.rgb = CHART_COLORS.get(
                    mat, FALLBACK_COL[i % len(FALLBACK_COL)]
                )
        except Exception as _e:
            print(f"Warning: bar chart slide skipped ({_e})")

    # ── Scatter chart slide ───────────────────────────────────────────────────
    _scat_pts = [
        (r.get("force_N"), r.get("resulting_contact_pressure_MPa"), r.get("material", ""))
        for r in rows
        if isinstance(r.get("force_N"), float)
        and isinstance(r.get("resulting_contact_pressure_MPa"), float)
        and r.get("material")
    ]
    if _scat_pts:
        try:
            from pptx.chart.data import XyChartData
            from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION

            sl = prs.slides.add_slide(blank)
            _bg(sl, 255, 255, 255)
            _txb(sl, 0.3, 0.08, 12.7, 0.6,
                 "Resulting Contact Pressure vs. Normal Force",
                 bold=True, sz=24, color=(31, 78, 121))
            _txb(sl, 0.3, 0.62, 12.7, 0.3,
                 "Resulting contact pressure = normal force / "
                 "(wear fraction × nominal ring area).",
                 sz=10, color=(130, 130, 130))

            SCAT_COLORS = {
                "INC718":  RGBColor(0,   114, 178),
                "INC625M": RGBColor(230, 159,   0),
            }
            SCAT_FALLBACK = [RGBColor(86, 180, 233), RGBColor(0, 158, 115)]

            scat_mats = sorted({pt[2] for pt in _scat_pts})
            cd = XyChartData()
            for mat in scat_mats:
                s = cd.add_series(mat)
                for force, rp, m in _scat_pts:
                    if m == mat:
                        s.add_data_point(force, rp)

            chart_shp = sl.shapes.add_chart(
                XL_CHART_TYPE.XY_SCATTER,
                Inches(0.4), Inches(1.0),
                Inches(12.5), Inches(6.2),
                cd,
            )
            chart = chart_shp.chart
            chart.has_title   = False
            chart.has_legend  = True
            chart.legend.position         = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False

            # Axes
            va = chart.value_axis
            va.minimum_scale = 0
            va.has_title = True
            va.axis_title.text_frame.text = "Resulting contact pressure (MPa)"

            ca = chart.category_axis
            ca.minimum_scale = 0
            ca.has_title = True
            ca.axis_title.text_frame.text = "Normal force (N)"

            # Marker colours per series
            for i, mat in enumerate(scat_mats):
                s = chart.series[i]
                col = SCAT_COLORS.get(mat, SCAT_FALLBACK[i % len(SCAT_FALLBACK)])
                s.marker.size = 10
                s.marker.format.fill.solid()
                s.marker.format.fill.fore_color.rgb = col
                s.marker.format.line.fill.background()
                s.format.line.fill.background()   # no connecting line

            # Add regression formula annotation as text box
            reg_lines = []
            for mat in scat_mats:
                mat_pts = [
                    (force, rp) for force, rp, m in _scat_pts if m == mat
                ]
                k, r2 = _regression_through_origin(mat_pts)
                if k is not None:
                    reg_lines.append(f"{mat}: p = {k:.4f}·F   R² = {r2:.4f}")
            if reg_lines:
                reg_text = "Regression through origin:\n" + "\n".join(reg_lines)
                _txb(sl, 0.3, 6.95, 12.7, 0.5, reg_text,
                     sz=10, color=(80, 80, 80))

        except Exception as _e:
            print(f"Warning: scatter chart slide skipped ({_e})")

    # ── Summary slide ─────────────────────────────────────────────────────────
    valid = sorted(
        [r for r in rows if isinstance(r.get("wear_fraction"), float)],
        key=lambda r: r["wear_fraction"], reverse=True,
    )
    sl = prs.slides.add_slide(blank)
    _bg(sl, 255, 255, 255)
    _txb(sl, 0.3, 0.08, 12.7, 0.6, "Summary – Wear Fraction Ranking",
         bold=True, sz=24, color=(31, 78, 121))

    hdrs  = ["Rank", "Test", "Material", "Force (N)", "Wear (%)",
             "Geo p (MPa)", "Res p (MPa)", "Flags"]
    col_w = [0.65, 0.95, 1.5, 0.85, 0.85, 1.1, 1.1, 5.65]
    n_rows = min(len(valid) + 1, 15)   # header + up to 14 data rows

    tbl = sl.shapes.add_table(
        n_rows, len(hdrs),
        Inches(0.25), Inches(0.78),
        Inches(13.0), Inches(0.42 * n_rows),
    ).table
    for ci, w in enumerate(col_w):
        tbl.columns[ci].width = Inches(w)

    def _cell(tbl, ri, ci, text, *, bold=False, sz=10,
              fg=(30, 30, 30), bg=None, align=PP_ALIGN.CENTER):
        cell = tbl.cell(ri, ci)
        cell.text = str(text) if text else " "
        para = cell.text_frame.paragraphs[0]
        para.alignment = align
        run = para.runs[0] if para.runs else para.add_run()
        run.font.bold  = bold
        run.font.size  = Pt(sz)
        run.font.color.rgb = RGBColor(*fg)
        if bg is not None:
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(*bg)

    for ci, h in enumerate(hdrs):
        _cell(tbl, 0, ci, h, bold=True, fg=(255, 255, 255), bg=(31, 78, 121))

    for ri, row in enumerate(valid[:14], 1):
        frac  = row.get("wear_fraction", 0)
        geo_p = row.get("geometric_contact_pressure_MPa")
        res_p = row.get("resulting_contact_pressure_MPa")
        fn    = row.get("force_N")
        row_bg = (232, 242, 251) if ri % 2 == 0 else None
        vals   = [
            str(ri),
            row.get("test_id", ""),
            row.get("material", ""),
            str(int(fn)) if isinstance(fn, float) else str(fn or ""),
            f"{frac*100:.1f}",
            f"{geo_p:.1f}" if geo_p else "–",
            f"{res_p:.1f}" if res_p else "–",
            row.get("flags", "") or "–",
        ]
        for ci, v in enumerate(vals):
            _cell(tbl, ri, ci, v, sz=10, bg=row_bg,
                  align=PP_ALIGN.LEFT if ci in (2, 7) else PP_ALIGN.CENTER)

    path = outdir / "results.pptx"
    prs.save(path)
    return path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def collect(inputs):
    files = []
    for s in inputs:
        q = Path(s)
        if q.is_dir():
            files += sorted(f for f in q.iterdir() if f.suffix.lower() in IMG_EXT)
        elif q.exists():
            files.append(q)
        else:
            files += sorted(Path().glob(s))
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description="Abschätzung heller Verschleißflächen auf Ring-Stirnflächen")
    ap.add_argument("inputs", nargs="+", help="Bilddateien, Ordner oder Glob-Muster")
    ap.add_argument("-o", "--out", default="ring_wear_out", help="Ausgabeordner")
    ap.add_argument("--bar-um", type=float, default=500.0, help="Länge des Maßstabsbalkens in µm")
    ap.add_argument("--um-per-px", type=float, default=None, help="Pixelgröße fest vorgeben")
    ap.add_argument("--nominal-area", type=float, default=43.2, help="Ringfläche in mm² (0 = aus)")
    ap.add_argument("--threshold-mode", choices=["adaptive", "fixed"], default="adaptive")
    ap.add_argument("--threshold", type=float, default=1.20, help="feste Schwelle (rel. Helligkeit)")
    ap.add_argument("--k-sigma", type=float, default=1.30, help="Faktor für adaptive Schwelle")
    ap.add_argument("--seam", choices=["auto", "none", "prior"], default="auto")
    ap.add_argument("--seam-offset", type=float, default=None,
                    help="Naht fest bei cx - offset·r_außen (setzt --seam prior)")
    ap.add_argument("--inner-margin-um", type=float, default=100.0)
    ap.add_argument("--outer-margin-um", type=float, default=100.0)
    ap.add_argument("--inner-diam-mm", type=float, default=3.0, help="nominaler Innendurchmesser / Bohrung (mm)")
    ap.add_argument("--outer-diam-mm", type=float, default=8.0, help="nominaler Außendurchmesser Ring (mm)")
    ap.add_argument("--panel", action="store_true", help="Variantenbild mit 4 Schwellen erzeugen")
    ap.add_argument("--keep-annotations", action="store_true", help="rote/blaue Markierungen nicht entfernen")
    ap.add_argument("--neu-dir", default=None,
                    help="Ordner mit Neuproben-Bildern (default: data/neu/ neben dem Input-Ordner)")
    a = ap.parse_args(argv)

    p = Params(bar_um=a.bar_um, um_per_px=a.um_per_px,
               nominal_area_mm2=(a.nominal_area or None),
               inner_diam_mm=a.inner_diam_mm, outer_diam_mm=a.outer_diam_mm,
               threshold_mode=a.threshold_mode, threshold=a.threshold, k_sigma=a.k_sigma,
               seam=("prior" if a.seam_offset is not None else a.seam),
               inner_margin_um=a.inner_margin_um, outer_margin_um=a.outer_margin_um,
               remove_annotations=not a.keep_annotations)
    if a.seam_offset is not None:
        p.seam_prior_offset = a.seam_offset

    files = collect(a.inputs)
    if not files:
        sys.exit("Keine Bilder gefunden.")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    # Locate new-probe folder (default: data/neu/ sibling of first input folder)
    if a.neu_dir:
        neu_dir = Path(a.neu_dir)
    else:
        first_parent = files[0].parent if files else Path(".")
        neu_dir = first_parent.parent / "neu"
    if not neu_dir.is_dir():
        neu_dir = None   # silently disable if not found

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except OSError:
            font = ImageFont.load_default()

    rows = []
    for f in files:
        try:
            res = analyse(f, p, out, panel=a.panel, font=font)

            # Store absolute paths for PPTX (never modify data/)
            res["_worn_abspath"] = str(f.resolve())

            # Find and copy new probe image to outdir (for HTML relative paths)
            mat = res.get("material", "")
            stem = Path(res["file"]).stem
            new_probe = _find_new_probe(mat, neu_dir)
            res["_new_probe_abspath"] = str(new_probe) if new_probe else None

            # Copy worn + new probe to outdir for HTML self-contained links
            worn_dest = _copy_image_to_outdir(f, out, f"{stem}_worn{f.suffix}")
            new_dest  = _copy_image_to_outdir(new_probe, out, f"{stem}_new.jpg") if new_probe else None
            res["_worn_outdir"]     = worn_dest.name  if worn_dest  else None
            res["_new_probe_outdir"] = new_dest.name  if new_dest   else None

            rows.append(res)
            ring_nom_val  = res.get("ring_area_nominal_mm2")
            ring_file     = res.get("sample_area_mm2")
            ring_analyzed = res.get("ring_area_analyzed_mm2")
            area_str = (
                f"  nominal={ring_nom_val:.1f} mm² (OD={p.outer_diam_mm}/ID={p.inner_diam_mm} mm, "
                f"filename={ring_file} mm²)  analyzed={ring_analyzed:.1f} mm² (image crop)"
                if ring_nom_val and ring_file else ""
            )
            print(f"{f.name:40s} {res['wear_fraction']*100:5.1f} %  T=+{(res['threshold']-1)*100:4.1f} %  "
                  f"Seam: {res['seam_status']:<20s}{area_str}  {res['flags']}")
        except Exception as e:  # ein defektes Bild soll den Batch nicht abbrechen
            rows.append(dict(file=f.name, flags=f"ERROR: {e}"))
            print(f"{f.name:40s} ERROR: {e}")

    keys = []
    for r_ in rows:
        keys += [k for k in r_ if k not in keys]
    with open(out / "results.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, delimiter=";")
        w.writeheader()
        for r_ in rows:
            w.writerow({k: (str(v).replace(".", ",") if isinstance(v, float) else v) for k, v in r_.items()})
    xlsx = write_excel(rows, out)
    html = write_html(rows, out)
    pptx = write_pptx(rows, out)
    (out / "params.json").write_text(json.dumps(asdict(p), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(rows)} images -> {out / 'results.csv'}")
    if xlsx:
        print(f"{len(rows)} images -> {xlsx}")
    print(f"{len(rows)} images -> {html}")
    if pptx:
        print(f"{len(rows)} images -> {pptx}")


if __name__ == "__main__":
    main()
