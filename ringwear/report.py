"""ringwear.report — Excel, HTML, and PPTX report writers."""
from __future__ import annotations

import math
from pathlib import Path

from .stats import (_bar_chart_data, _bar_chart_svg, _regression_through_origin,
                    _scatter_svg, _group_stats)


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
        "Repeat n", "Repeat std (pp)",
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
            row.get("repeat_n", ""),
            (round(row["repeat_std"] * 100, 3)
             if isinstance(row.get("repeat_std"), float) and not math.isnan(row["repeat_std"])
             else ""),
            row.get("um_per_px", ""),
            row.get("threshold", ""),
            row.get("seam_status", ""),
            row.get("flags", ""),
        ])

    for col in ws.columns:
        width = max((len(str(c.value or "")) for c in col), default=8) + 2
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(width, 50)

    ws.freeze_panes = "A2"

    path = outdir / "results.xlsx"
    wb.save(path)
    return path


# --------------------------------------------------------------------------- #
# HTML report (stdlib only – no extra dependencies)
# --------------------------------------------------------------------------- #
def _img_b64_src(path: "Path | None") -> "str | None":
    """Return a base64 data URI for *path*, or None if the file is missing."""
    import base64
    if path is None or not Path(path).exists():
        return None
    p = Path(path)
    mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png",
                ".tif": "tiff", ".tiff": "tiff", ".bmp": "bmp"}
    mime = mime_map.get(p.suffix.lower(), "png")
    return f"data:image/{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def write_html(rows: list, outdir: Path) -> Path:
    """Standalone HTML report — all images embedded as base64 data URIs."""
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

    sum_rows = []
    for rank, row in enumerate(valid, 1):
        frac   = row["wear_fraction"]
        cls    = wear_cls(frac)
        geo_p  = row.get("geometric_contact_pressure_MPa")
        res_p  = row.get("resulting_contact_pressure_MPa")
        wear_a = row.get("wear_area_mm2")
        flags  = esc(row.get("flags") or "")
        flag_td = f'<span class="flag-warn">{flags}</span>' if flags and flags != "–" else "–"
        # Uncertainty suffix for summary table: prefer repeat std, fall back to method band
        rpt_std = row.get("repeat_std")
        rpt_n   = row.get("repeat_n")
        fmin_s  = row.get("wear_fraction_min")
        fmax_s  = row.get("wear_fraction_max")
        if isinstance(rpt_std, float) and not math.isnan(rpt_std) and isinstance(rpt_n, int) and rpt_n >= 2:
            unc_sfx = (f'<br><span style="color:#888;font-size:.82em">'
                       f'±{rpt_std*100:.1f} pp (n={rpt_n})</span>')
        elif fmin_s is not None and fmax_s is not None:
            unc_sfx = (f'<br><span style="color:#888;font-size:.82em">'
                       f'±{(fmax_s-fmin_s)/2*100:.1f} pp</span>')
        else:
            unc_sfx = ""
        sum_rows.append(
            f"<tr>"
            f"<td>{rank}</td>"
            f"<td>{esc(row.get('test_id'))}</td>"
            f"<td>{esc(row.get('material'))}</td>"
            f"<td>{esc(row.get('force_N'))}</td>"
            f"<td class='{cls}'><b>{frac*100:.1f}</b>{unc_sfx}</td>"
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

    cards = []
    for row in rows:
        if not isinstance(row.get("wear_fraction"), float):
            continue
        stem       = Path(row.get("file", "")).stem
        new_path   = row.get("_new_probe_outdir")
        worn_path  = row.get("_worn_outdir")
        ov_file    = f"{stem}_overlay.png"
        def _img(fname, alt, caption):
            src = _img_b64_src(outdir / fname if fname else None)
            tag = (f'<img src="{src}" alt="{esc(alt)}">'
                   if src else f'<div class="img-missing">{esc(alt)}<br>not found</div>')
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

        # Uncertainty: prefer repeat std (random, from N reps), fall back to method band (systematic)
        fmin   = row.get("wear_fraction_min")
        fmax   = row.get("wear_fraction_max")
        a_nom  = row.get("ring_area_nominal_mm2")
        force  = row.get("force_N")
        rpt_std = row.get("repeat_std")
        rpt_n   = row.get("repeat_n")
        _pp = ('<abbr title="percentage points — absolute difference, e.g. ±1 pp at 18 % '
               'means 17–19 %">pp</abbr>')

        use_repeat = (isinstance(rpt_std, float) and not math.isnan(rpt_std)
                      and isinstance(rpt_n, int) and rpt_n >= 2)

        if use_repeat:
            _UNC = (f'<span style="color:#888;font-size:.88em">'
                    f' (±1σ, {rpt_n} reps)</span>')
            half_pp = rpt_std * 100
            frac_unc = (f'<span class="{cls}"><b>{frac*100:.1f} %</b></span>'
                        f' ± {half_pp:.1f} {_pp}{_UNC}')
            if wear_a is not None:
                a_anal = row.get("ring_area_analyzed_mm2") or 0.0
                wear_a_half = rpt_std * a_anal
                wear_a_str = f"{wear_a:.3f} mm² ± {wear_a_half:.3f} mm²{_UNC}"
            else:
                wear_a_str = "–"
            if res_p is not None and frac > 0 and a_nom and force:
                # Gaussian propagation: σ_p = p × σ_frac / frac
                p_sigma = res_p * rpt_std / frac
                res_p_str = f"{res_p:.1f} MPa ± {p_sigma:.1f} MPa{_UNC}"
            elif res_p is not None:
                res_p_str = f"{res_p:.1f} MPa"
            else:
                res_p_str = "–"
        elif fmin is not None and fmax is not None:
            _UNC = '<span style="color:#888;font-size:.88em"> (systematic)</span>'
            half_pp = (fmax - fmin) / 2 * 100
            frac_unc = (f'<span class="{cls}"><b>{frac*100:.1f} %</b></span>'
                        f' ± {half_pp:.1f} {_pp}{_UNC}')
            if wear_a is not None:
                area_analyzed = row.get("ring_area_analyzed_mm2") or 0.0
                wear_a_half = (fmax - fmin) / 2 * area_analyzed
                wear_a_str = f"{wear_a:.3f} mm² ± {wear_a_half:.3f} mm²{_UNC}"
            else:
                wear_a_str = "–"
            if res_p is not None and fmin is not None and fmax is not None and a_nom and force:
                rp_lo = force / (fmax * a_nom)
                rp_hi = force / (fmin * a_nom)
                res_p_str = f"{res_p:.1f} MPa ± {(rp_hi - rp_lo)/2:.1f} MPa{_UNC}"
            elif res_p is not None:
                res_p_str = f"{res_p:.1f} MPa"
            else:
                res_p_str = "–"
        else:
            frac_unc  = f'<span class="{cls}"><b>{frac*100:.1f} %</b></span>'
            wear_a_str = f"{wear_a:.3f} mm²" if wear_a is not None else "–"
            res_p_str  = f"{res_p:.1f} MPa"  if res_p  is not None else "–"

        rpt_n_v = row.get("repeat_n")
        rpt_note = (f'<span style="color:#888;font-size:.85em"> — mean of {rpt_n_v} repetitions</span>'
                    if isinstance(rpt_n_v, int) and rpt_n_v > 1 else "")
        metrics = [
            ("Wear fraction",         frac_unc),
            ("Wear area (analyzed)",  wear_a_str),
            ("Ring area nominal",     f"{esc(a_nom)} mm²"),
            ("Ring area analyzed",    f"{esc(row.get('ring_area_analyzed_mm2'))} mm²"),
            ("Bore Ø measured",       f"{esc(row.get('bore_diameter_measured_mm'))} mm"),
            ("Geometric pressure",    f"{geo_p:.1f} MPa"  if geo_p else "–"),
            ("Resulting pressure",    res_p_str),
            ("µm/px",                 esc(row.get("um_per_px"))),
            ("Threshold",             esc(row.get("threshold"))),
            ("Seam",                  esc(row.get("seam_status"))),
            ("Flags",                 flag_val),
        ]
        mrows = "".join(f"<tr><td>{label}</td><td>{val}</td></tr>" for label, val in metrics)
        title = (f"{esc(row.get('test_id','?'))}{rpt_note}"
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
        ".method-box{background:#f5f8fc;border-left:4px solid #1f4e79;border-radius:4px;"
        "padding:16px 20px;margin-top:12px}"
        ".method-box ol{margin:0;padding-left:1.4em}"
        ".method-box li{margin-bottom:8px;line-height:1.5}"
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
            "Wear area = wear fraction × nominal ring area (43.2 mm²). "
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
<p style="color:#888;font-size:.8em;margin-top:6px">
  ± values in <em>Wear (%)</em> column are in
  <abbr title="percentage points — absolute difference between two percentages, e.g. 18 % ± 1 pp means the true value lies between 17 % and 19 %">pp (percentage points)</abbr>.
  When multiple repetitions per experiment are available: ±1σ from repeat measurements (n shown in parentheses).
  Otherwise: systematic uncertainty from 54-combination parameter grid sweep.
</p>
{chart_block}
<h2>Details</h2>
{"".join(cards)}

<h2>Detection Method</h2>
<div class="method-box">
<ol>
<li><strong>Scale calibration</strong> — white reference box (bottom-right corner) detected
automatically. Pixel size derived from nominal bar length (500&nbsp;µm).</li>
<li><strong>Ring geometry</strong> — inner bore and outer boundary located as dark connected
regions. Evaluation mask = annular zone shrunk by 100&nbsp;µm on each side to exclude
edge artefacts.</li>
<li><strong>Seam removal</strong> — brightest arc excluded (±15°) to prevent weld or clamping
reflection from being counted as wear.</li>
<li><strong>Sector-normalised brightness (<em>rel</em>)</strong> — each pixel divided by the
median brightness of its own half-ring. Cancels illumination gradients and vignetting.</li>
<li><strong>Adaptive threshold</strong> T = 1 + k<sub>σ</sub> × σ<sub>rob</sub>
(default k<sub>σ</sub> = 1.30, σ<sub>rob</sub> = IQR/1.35 of <em>rel</em>).
Pixels with rel &gt; T are classified as bright (worn).</li>
<li><strong>Texture criterion</strong> — local standard-deviation map (~44&nbsp;µm window).
Smooth zones (tex_rel &lt; 0.42) classified as polished (worn). Final mask = union of
brightness and texture criteria, morphologically cleaned.</li>
<li><strong>Wear fraction</strong> = worn pixels / evaluation pixels.
<strong>Method band</strong> from 54-combination parameter grid sweep (systematic uncertainty,
shown as dashed rectangle in charts).</li>
</ol>
<p style="color:#888;font-size:.85em">
Full technical description: <code>docs/method_description.md</code></p>
</div>
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
    blank = prs.slide_layouts[6]

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

    # ── Title slide
    sl = prs.slides.add_slide(blank)
    _bg(sl, 31, 78, 121)
    _txb(sl, 0.5, 2.0, 12.3, 1.3, "Ring Wear Analysis Report",
         bold=True, sz=38, color=(255, 255, 255), align=PP_ALIGN.CENTER)
    n_ok = sum(1 for r in rows if isinstance(r.get("wear_fraction"), float))
    sub  = (f"Generated {datetime.date.today().isoformat()}"
            f"  ·  {n_ok} of {len(rows)} images analysed")
    _txb(sl, 0.5, 3.5, 12.3, 0.7, sub, sz=18,
         color=(180, 215, 245), align=PP_ALIGN.CENTER)

    # ── Method description slide
    sl = prs.slides.add_slide(blank)
    _bg(sl, 255, 255, 255)
    _txb(sl, 0.4, 0.08, 12.5, 0.55, "Detection Method",
         bold=True, sz=22, color=(31, 78, 121))
    method_text = (
        "1  Scale calibration — white reference box (bottom-right) detected automatically; "
        "pixel size derived from nominal bar length (500 µm).\n\n"
        "2  Ring geometry — inner bore and outer boundary located as dark connected regions; "
        "evaluation mask = annular zone shrunk by 100 µm on each side.\n\n"
        "3  Seam removal — brightest arc excluded (±15°) to prevent weld/clamp reflection "
        "being counted as wear.\n\n"
        "4  Sector-normalised brightness (rel) — each pixel divided by its half-ring median; "
        "cancels illumination gradients and vignetting.\n\n"
        "5  Adaptive threshold  T = 1 + kσ × σ_rob  (default kσ = 1.30); "
        "pixels with rel > T classified as bright (worn).\n\n"
        "6  Texture criterion — local std-dev map (~44 µm window); "
        "smooth zones (tex_rel < 0.42) classified as polished (worn).\n\n"
        "7  Wear fraction = worn pixels / evaluation pixels.  "
        "Method band from 54-parameter grid sweep (systematic uncertainty, shown dashed).\n\n"
        "Uncertainty notation used in this report:\n"
        "  ±N pp  =  ±N percentage points  (1σ from repeat measurements, when n ≥ 2)\n"
        "             e.g. 18.4 % ± 1.0 pp (n=3)  →  std across 3 repetitions = 1.0 pp\n"
        "  ±N mm² / ±N MPa  =  same uncertainty propagated to wear area and contact pressure\n"
        "  Fallback (single image): systematic uncertainty from 54-combination parameter grid sweep"
    )
    _txb(sl, 0.4, 0.75, 12.5, 6.5, method_text, sz=11, color=(40, 40, 40))

    # ── Per-experiment slides
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

        IMG_CAPTIONS = ["② Worn probe", "① New probe (unworn)", "③ Wear detected"]
        img_specs = [
            row.get("_worn_abspath"),
            row.get("_new_probe_abspath"),
            str(outdir / f"{stem}_overlay.png"),
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

        frac     = row.get("wear_fraction", 0.0)
        geo_p    = row.get("geometric_contact_pressure_MPa")
        res_p    = row.get("resulting_contact_pressure_MPa")
        wear_a   = row.get("wear_area_mm2")
        fmin_p   = row.get("wear_fraction_min")
        fmax_p   = row.get("wear_fraction_max")
        a_nom_p  = row.get("ring_area_nominal_mm2")
        force_p  = row.get("force_N")
        a_anal_p = row.get("ring_area_analyzed_mm2") or 0.0
        rpt_std_p = row.get("repeat_std")
        rpt_n_p   = row.get("repeat_n")

        use_rep_p = (isinstance(rpt_std_p, float) and not math.isnan(rpt_std_p)
                     and isinstance(rpt_n_p, int) and rpt_n_p >= 2)

        if use_rep_p:
            # Random uncertainty from repeat measurements
            frac_str    = f"{frac*100:.1f} %  ±{rpt_std_p*100:.1f} pp (n={rpt_n_p})"
            wear_a_str_p = (f"{wear_a:.3f}  ±{rpt_std_p * a_anal_p:.3f} mm²  (n={rpt_n_p})"
                            if wear_a else "–")
            if res_p and frac > 0:
                p_sigma_p = res_p * rpt_std_p / frac
                res_p_str_p = f"{res_p:.1f}  ±{p_sigma_p:.1f} MPa  (n={rpt_n_p})"
            else:
                res_p_str_p = f"{res_p:.1f} MPa" if res_p else "–"
        elif fmin_p is not None and fmax_p is not None:
            # Systematic uncertainty from method band
            half_pp_p = (fmax_p - fmin_p) / 2 * 100
            frac_str    = f"{frac*100:.1f} %  ±{half_pp_p:.1f} pp"
            wear_a_str_p = (f"{wear_a:.3f}  ±{(fmax_p - fmin_p)/2 * a_anal_p:.3f} mm²"
                            if wear_a else "–")
            if res_p and a_nom_p and force_p:
                rp_lo_p = force_p / (fmax_p * a_nom_p)
                rp_hi_p = force_p / (fmin_p * a_nom_p)
                res_p_str_p = f"{res_p:.1f}  ±{(rp_hi_p - rp_lo_p)/2:.1f} MPa"
            else:
                res_p_str_p = f"{res_p:.1f} MPa" if res_p else "–"
        else:
            frac_str    = f"{frac*100:.1f} %"
            wear_a_str_p = f"{wear_a:.3f} mm²" if wear_a else "–"
            res_p_str_p  = f"{res_p:.1f} MPa"  if res_p  else "–"

        mx = 8.35
        lines = [
            ("Wear fraction",        frac_str),
            ("Wear area (analyzed)", wear_a_str_p),
            ("Geometric pressure",   f"{geo_p:.1f} MPa"  if geo_p  else "–"),
            ("Resulting pressure",   res_p_str_p),
            ("Bore Ø measured",      f"{row.get('bore_diameter_measured_mm','–')} mm"),
            ("Ring area nominal",    f"{a_nom_p or '–'} mm²"),
            ("Ring area analyzed",   f"{a_anal_p or '–'} mm²"),
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

    # ── Bar chart slide
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

            va = chart.value_axis
            va.minimum_scale = 0
            va.has_title = True
            va.axis_title.text_frame.text = "Wear area (mm²)"

            ca = chart.category_axis
            ca.has_title = True
            ca.axis_title.text_frame.text = "Normal force (N)"

            for i, mat in enumerate(list(_series.keys())):
                s = chart.series[i]
                s.format.fill.solid()
                s.format.fill.fore_color.rgb = CHART_COLORS.get(
                    mat, FALLBACK_COL[i % len(FALLBACK_COL)]
                )
        except Exception as _e:
            print(f"Warning: bar chart slide skipped ({_e})")

    # ── Scatter chart slide
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

            va = chart.value_axis
            va.minimum_scale = 0
            va.has_title = True
            va.axis_title.text_frame.text = "Resulting contact pressure (MPa)"

            ca = chart.category_axis
            ca.minimum_scale = 0
            ca.has_title = True
            ca.axis_title.text_frame.text = "Normal force (N)"

            for i, mat in enumerate(scat_mats):
                s = chart.series[i]
                col = SCAT_COLORS.get(mat, SCAT_FALLBACK[i % len(SCAT_FALLBACK)])
                s.marker.size = 10
                s.marker.format.fill.solid()
                s.marker.format.fill.fore_color.rgb = col
                s.marker.format.line.fill.background()
                s.format.line.fill.background()

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

    # ── Summary slide
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
    n_rows = min(len(valid) + 1, 15)

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
