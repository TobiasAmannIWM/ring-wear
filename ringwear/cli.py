"""ringwear.cli — command-line interface."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

from PIL import ImageFont

from .core import Params, IMG_EXT, analyse
from .report import write_excel, write_html, write_pptx
from .stats import _find_new_probe, _copy_image_to_outdir


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
        neu_dir = None

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

            res["_worn_abspath"] = str(f.resolve())

            mat = res.get("material", "")
            stem = Path(res["file"]).stem
            new_probe = _find_new_probe(mat, neu_dir)
            res["_new_probe_abspath"] = str(new_probe) if new_probe else None

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
        except Exception as e:
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
