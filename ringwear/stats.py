"""ringwear.stats — statistics helpers, chart data builders, SVG renderers."""
from __future__ import annotations

import shutil
import statistics as _st
from collections import defaultdict
from pathlib import Path


def _group_stats(rows):
    """Group rows by (force_N, material) and return mean ± std for each group.

    wear_area tuple: (mean, std, n, band_min, band_max)
      band_min / band_max = min/max across method band for all experiments in group.
      band_min / band_max are None when no sensitivity grid was run.
    resulting_p tuple: (mean, std, n)
    """
    groups: dict = defaultdict(lambda: {"wa": [], "rp": [], "wa_bmin": [], "wa_bmax": []})
    for row in rows:
        frac     = row.get("wear_fraction")
        fmin     = row.get("wear_fraction_min")
        fmax     = row.get("wear_fraction_max")
        force    = row.get("force_N")
        mat      = row.get("material")
        nom_area = row.get("ring_area_nominal_mm2")
        res_p    = row.get("resulting_contact_pressure_MPa")
        if not isinstance(frac, float) or force is None or not mat or not nom_area:
            continue
        area = frac * nom_area
        g = groups[(float(force), mat)]
        g["wa"].append(area)
        if isinstance(fmin, float):
            g["wa_bmin"].append(fmin * nom_area)
        if isinstance(fmax, float):
            g["wa_bmax"].append(fmax * nom_area)
        if isinstance(res_p, float):
            g["rp"].append(res_p)
    result = {}
    for key, data in groups.items():
        wa = data["wa"]
        rp = data["rp"]
        bmin_list = data["wa_bmin"]
        bmax_list = data["wa_bmax"]
        band_min = min(bmin_list) if bmin_list else None
        band_max = max(bmax_list) if bmax_list else None
        result[key] = {
            "wear_area":   (sum(wa)/len(wa),
                            _st.stdev(wa) if len(wa) >= 2 else 0.0,
                            len(wa),
                            band_min,
                            band_max),
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
    for sub in neu_dir.iterdir():
        if sub.is_dir() and sub.name.lower() == material.lower():
            for f in sorted(sub.iterdir()):
                if f.suffix.lower() in IMG_EXT_SET:
                    return f
    for f in sorted(neu_dir.iterdir()):
        if f.suffix.lower() in IMG_EXT_SET and material.lower() in f.stem.lower():
            return f
    return None


def _copy_image_to_outdir(src: "Path", outdir: "Path", dest_name: str) -> "Path | None":
    """Copy *src* to *outdir/dest_name*; return dest path, or None on failure."""
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
    """Return (categories, series_dict) for a grouped bar chart with std and method band."""
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
    """Grouped bar chart with mean bars, ±std error bars, and dashed method band (HTML SVG).

    Dashed grey band: systematic uncertainty (method band min–max from parameter grid).
    Solid error bar: random uncertainty (±1 std across repeated experiments, n≥2).
    The two are shown SEPARATELY — never quadratically combined.
    """
    categories, series_dict = _bar_chart_data(rows)
    if not categories or not series_dict:
        return ""

    # 5-tuple: (mean, std, n, band_min, band_max)
    all_means = [tup[0] for vals in series_dict.values() for tup in vals if tup is not None]
    all_stds  = [tup[1] for vals in series_dict.values() for tup in vals if tup is not None]
    all_bmaxs = [tup[4] for vals in series_dict.values() for tup in vals
                 if tup is not None and tup[4] is not None]
    if not all_means:
        return ""

    has_band = bool(all_bmaxs)

    W, H = 820, 460
    PAD_L, PAD_R, PAD_T, PAD_B = 72, 170, 55, 80
    PW = W - PAD_L - PAD_R
    PH = H - PAD_T - PAD_B

    max_top = max(all_bmaxs) if has_band else max(m + s for m, s in zip(all_means, all_stds))
    max_val = max_top * 1.25

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
    subtitle = ("Dashed: method band min–max (systematic, assumption). "
                "Solid: ±std (random, n≥2 repeats)." if has_band else
                "Solid error bars: ±1 std dev across repeated experiments.")
    p.append(f'<text x="{W//2}" y="49" text-anchor="middle" font-size="10" fill="#888">'
             f'{subtitle}</text>')

    yl_x, yl_y = 14, PAD_T + PH // 2
    p.append(f'<text x="{yl_x}" y="{yl_y}" text-anchor="middle" font-size="11" '
             f'fill="#555" transform="rotate(-90 {yl_x} {yl_y})">Wear area (mm²)</text>')
    p.append(f'<text x="{PAD_L + PW//2}" y="{H - 20}" text-anchor="middle" '
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
            mean_v, std_v, n_v, band_min, band_max = tup
            bx    = bar_start + si * (bar_w + bar_gap)
            bcx   = bx + bar_w / 2
            by    = ypx(mean_v)
            bh    = PAD_T + PH - by
            col   = colors[si]

            # Dashed method band (drawn first, behind the bar)
            if band_min is not None and band_max is not None:
                y_bmin = min(ypx(max(band_min, 0.0)), PAD_T + PH)
                y_bmax = ypx(min(band_max, max_val))
                band_hw = bar_w * 0.55
                p.append(f'<rect x="{bcx - band_hw:.1f}" y="{y_bmax:.1f}" '
                         f'width="{2 * band_hw:.1f}" height="{y_bmin - y_bmax:.1f}" '
                         f'fill="none" stroke="#888" stroke-width="1.2" '
                         f'stroke-dasharray="4,3" rx="1" opacity="0.8"/>')

            p.append(f'<rect x="{bx:.1f}" y="{by:.1f}" '
                     f'width="{bar_w:.1f}" height="{bh:.1f}" '
                     f'fill="{col}" opacity="0.9" rx="2"/>')

            if bh > 14:
                lbl = f"{mean_v:.2f}" if n_v < 2 else f"{mean_v:.2f}±{std_v:.2f}"
                p.append(f'<text x="{bcx:.1f}" y="{by - 5:.1f}" '
                         f'text-anchor="middle" font-size="9" '
                         f'fill="{col}" font-weight="bold">{lbl}</text>')

            # Solid ±std error bar (random uncertainty, n≥2 only)
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
                p.append(f'<text x="{bcx:.1f}" y="{PAD_T+PH+32}" '
                         f'text-anchor="middle" font-size="9" fill="#888">n={n_v}</text>')

    lx, ly = PAD_L + PW + 20, PAD_T + 10
    for si, mat in enumerate(mats):
        yl = ly + si * 24
        p.append(f'<rect x="{lx}" y="{yl}" width="16" height="16" '
                 f'fill="{colors[si]}" rx="3"/>')
        p.append(f'<text x="{lx + 22}" y="{yl + 12}" '
                 f'font-size="12" fill="#333">{mat}</text>')

    if has_band:
        yl = ly + n_ser * 24 + 12
        p.append(f'<rect x="{lx}" y="{yl}" width="16" height="12" fill="none" '
                 f'stroke="#888" stroke-dasharray="4,3" stroke-width="1.2" rx="1"/>')
        p.append(f'<text x="{lx + 22}" y="{yl + 10}" font-size="10" fill="#666">'
                 f'Method band</text>')

    p.append('</svg>')
    return "\n".join(p)


def _scatter_svg(rows):
    """Scatter plot with regression through origin, error bars, and method band.

    For each experiment with a method band (wear_fraction_min/max), a vertical
    dashed grey line shows the resulting-pressure range [rp_lo, rp_hi] where
    rp_lo = F / (fmax × A_nom) and rp_hi = F / (fmin × A_nom).
    """
    pts = []
    for row in rows:
        force    = row.get("force_N")
        rp       = row.get("resulting_contact_pressure_MPa")
        mat      = row.get("material")
        tid      = row.get("test_id", "")
        nom_area = row.get("ring_area_nominal_mm2")
        fmin     = row.get("wear_fraction_min")
        fmax     = row.get("wear_fraction_max")
        if isinstance(force, float) and isinstance(rp, float) and mat:
            rp_lo = (force / (fmax * nom_area)
                     if isinstance(fmax, float) and fmax > 0 and nom_area else None)
            rp_hi = (force / (fmin * nom_area)
                     if isinstance(fmin, float) and fmin > 0 and nom_area else None)
            pts.append((force, rp, mat, tid, rp_lo, rp_hi))
    if not pts:
        return ""

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

    reg = {}
    for mat in mats:
        mat_pts = [(f, rp) for f, rp, m, _tid, _rlo, _rhi in pts if m == mat]
        k, r2 = _regression_through_origin(mat_pts)
        if k is not None:
            reg[mat] = (k, r2)

    has_band = any(pt[4] is not None for pt in pts)

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
    scatter_sub = ("Dashed lines: regression. Colored dashed bars: method band (systematic). Solid bars: ±std (repetitions)."
                   if has_band else
                   "Dashed lines: regression through origin  ·  Error bars: ±1 std dev")
    p.append(
        f'<text x="{W//2}" y="49" text-anchor="middle" font-size="10" fill="#888">'
        f'{scatter_sub}</text>'
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

    for mat in mats:
        if mat not in reg:
            continue
        k, r2 = reg[mat]
        col = colors.get(mat, "#888")
        x0, x1_v = 0.0, x_max
        y0_v = k * x0
        y1_v = k * x1_v
        if y1_v > y_max:
            x1_v = y_max / k
            y1_v = y_max
        rxp0, ryp0 = xpx(x0), ypx(y0_v)
        rxp1, ryp1 = xpx(x1_v), ypx(y1_v)
        p.append(
            f'<line x1="{rxp0:.1f}" y1="{PAD_T+PH:.1f}" '
            f'x2="{rxp1:.1f}" y2="{ryp1:.1f}" '
            f'stroke="{col}" stroke-width="1.8" stroke-dasharray="6,4" opacity="0.7"/>'
        )

    # Build offset map: experiments sharing a force value are spread apart by material
    force_mats: dict[float, list[str]] = {}
    for force, rp, mat, tid, rp_lo, rp_hi in pts:
        force_mats.setdefault(force, [])
        if mat not in force_mats[force]:
            force_mats[force].append(mat)

    for (force, mat), gdata in stats.items():
        rp_data = gdata.get("resulting_p")
        if rp_data is None:
            continue
        mean_rp, std_rp, n_rp = rp_data
        if n_rp < 2 or std_rp <= 0:
            continue
        col  = colors.get(mat, "#888")
        idx  = force_mats.get(force, [mat]).index(mat) if mat in force_mats.get(force, []) else 0
        n_at = len(force_mats.get(force, [mat]))
        x_off = (idx - (n_at - 1) / 2) * 11
        xc   = xpx(force) + x_off
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

    R = 6
    # Method band per experiment — colored by material so bars are attributable
    for force, rp, mat, tid, rp_lo, rp_hi in pts:
        if rp_lo is None or rp_hi is None:
            continue
        col = colors.get(mat, "#888")
        # slight x-offset when two materials share the same force value
        idx = force_mats[force].index(mat)
        x_off = (idx - (len(force_mats[force]) - 1) / 2) * 11
        xc = xpx(force) + x_off
        y_lo = min(ypx(max(rp_lo, 0.0)), PAD_T + PH)
        y_hi = ypx(min(rp_hi, y_max))
        p.append(f'<line x1="{xc:.1f}" y1="{y_hi:.1f}" x2="{xc:.1f}" y2="{y_lo:.1f}" '
                 f'stroke="{col}" stroke-width="4" stroke-dasharray="4,3" opacity="0.45"/>')

    for force, rp, mat, tid, rp_lo, rp_hi in pts:
        col = colors.get(mat, "#888")
        idx = force_mats.get(force, [mat]).index(mat) if mat in force_mats.get(force, []) else 0
        n_at = len(force_mats.get(force, [mat]))
        x_off = (idx - (n_at - 1) / 2) * 11
        xc, yc = xpx(force) + x_off, ypx(rp)
        p.append(
            f'<circle cx="{xc:.1f}" cy="{yc:.1f}" r="{R}" '
            f'fill="{col}" opacity="0.85" stroke="white" stroke-width="1.5"/>'
        )

    for force, rp, mat, tid, rp_lo, rp_hi in pts:
        col = colors.get(mat, "#888")
        idx = force_mats.get(force, [mat]).index(mat) if mat in force_mats.get(force, []) else 0
        n_at = len(force_mats.get(force, [mat]))
        x_off = (idx - (n_at - 1) / 2) * 11
        xc, yc = xpx(force) + x_off, ypx(rp)
        if tid:
            lx_lbl = xc + R + 4 if xc < PAD_L + PW * 0.85 else xc - R - 4
            anchor = "start" if xc < PAD_L + PW * 0.85 else "end"
            p.append(
                f'<text x="{lx_lbl:.1f}" y="{yc + 4:.1f}" '
                f'font-size="10" fill="{col}" text-anchor="{anchor}">{tid}</text>'
            )

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
