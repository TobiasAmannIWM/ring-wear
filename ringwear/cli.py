"""ringwear.cli — command-line interface."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics as _statistics
import sys
from dataclasses import asdict
from pathlib import Path

from PIL import ImageFont

from .core import Params, IMG_EXT, analyse
from .report import write_excel, write_html, write_pptx
from .stats import _find_new_probe, _copy_image_to_outdir
from . import sensitivity as _sens
from . import manifest as _manifest
from . import repeat as _repeat
from . import before_after as _ba


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


def _cmd_repeat(args) -> int:
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"ERROR: '{folder}' is not a directory.", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    neu_dir = Path(args.neu_dir) if args.neu_dir else None

    # Load sensitivity grid (same auto-discovery as main analysis)
    sens_grid, sens_best = None, None
    if not args.no_sensitivity:
        candidates = [
            folder / "sensitivity_grid.json",
            folder.parent / "sensitivity_grid.json",
            Path("sensitivity_grid.json"),
        ]
        for c in candidates:
            if c.exists():
                try:
                    sens_grid, sens_best = _sens.load_grid(c)
                    n_combos = (len(sens_grid.get("k_sigma", [])) *
                                len(sens_grid.get("tex_low_thr", [])) *
                                len(sens_grid.get("tex_min_rel", [])))
                    print(f"[sensitivity] grid: {c.name}  {n_combos} combinations")
                except Exception as e:
                    print(f"[sensitivity] WARNING: could not load {c}: {e}")
                break

    p = Params()  # default params (k_sigma=1.30, adaptive)

    result = _repeat.run_repeat(
        folder, p, out,
        sensitivity_grid=sens_grid,
        sensitivity_best=sens_best,
        neu_folder=neu_dir,
    )

    _repeat.print_report(result)
    csv_path = _repeat.write_repeat_csv(result, out)
    print(f"\nResults written to: {csv_path}")
    return 0


def _cmd_before_after(args) -> int:
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"ERROR: '{folder}' is not a directory.", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    p = Params()  # default params
    result = _ba.run_before_after(folder, p, out)

    _ba.print_report(result)
    csv_path = _ba.write_before_after_csv(result, out)
    print(f"\nResults written to: {csv_path}")

    if result.n_paired == 0:
        print("[INFO] No vor/nach pairs found — check manifest.csv or filename zustand-tokens.")
    return 0


def _cmd_manifest_init(args) -> int:
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"ERROR: '{folder}' is not a directory.", file=sys.stderr)
        return 1
    try:
        out, warnings = _manifest.init_manifest(folder)
    except FileExistsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"[manifest] WARNING: {w}")
    print(f"[manifest] Written: {out}  ({_count_lines(out)-1} image entries)")
    print(f"[manifest] Edit the file to set probe IDs, zustand, wiederholung, winkel_deg, sitzung.")
    return 0


def _count_lines(path: Path) -> int:
    with open(path, encoding="utf-8-sig") as fh:
        return sum(1 for _ in fh)


def _cmd_manifest_validate(args) -> int:
    folder = Path(args.folder)
    rows, load_warnings = _manifest.load_manifest(folder)
    for w in load_warnings:
        print(f"[manifest] WARNING: {w}")
    errors = _manifest.validate(rows, folder)
    if errors:
        for e in errors:
            print(f"[manifest] ERROR: {e}", file=sys.stderr)
        print(f"[manifest] {len(errors)} error(s) found in {folder / 'manifest.csv'}")
        return 1
    print(f"[manifest] OK — {len(rows)} entries, no errors ({folder / 'manifest.csv'})")
    return 0


def _group_files_by_probe(files):
    """Group input files by probe ID using manifest or filename parsing.

    Returns an OrderedDict[probe_key → list[Path]] preserving input order.
    Probes with 1 file (old convention, no repeats) produce single-element lists.
    Probe key format: "{folder_path}::{probe_id}" (with manifest) or str(path) (no manifest).
    """
    from collections import OrderedDict
    from . import manifest as _M

    folder_manifests: dict = {}

    def _get_row(f: Path):
        folder = f.parent
        if folder not in folder_manifests:
            rows, _ = _M.load_manifest(folder)
            folder_manifests[folder] = {r.datei: r for r in rows}
        return folder_manifests[f.parent].get(f.name)

    grouped: dict = OrderedDict()
    for f in files:
        row = _get_row(f)
        if row is not None and row.zustand != "neu":
            key = f"{f.parent}::{row.probe}"
        else:
            key = str(f)
        grouped.setdefault(key, [])
        grouped[key].append(f)
    return grouped


def _aggregate_probe_results(probe_key: str, probe_files: list, sub_results: list) -> dict:
    """Merge multiple repetition results into one aggregated output row.

    The representative value is the mean wear_fraction across valid repetitions.
    repeat_std  = std of wear_fraction across reps (random measurement uncertainty).
    wear_fraction_min/max = sensitivity-band envelope across all reps.
    All three individual measurements are used only here (internal calibration);
    only this one aggregated row goes into the output.
    """
    good = [r for r in sub_results
            if isinstance(r.get("wear_fraction"), float)
            and not math.isnan(r["wear_fraction"])]
    if not good:
        flags_all = "; ".join(r.get("flags", "ERROR") for r in sub_results)
        name = probe_key.split("::")[-1] if "::" in probe_key else Path(probe_key).name
        return {"file": name, "flags": f"ERROR: all {len(sub_results)} repetitions failed — {flags_all}"}

    n = len(good)
    fracs = [r["wear_fraction"] for r in good]
    mean_frac = sum(fracs) / n
    std_frac = _statistics.stdev(fracs) if n >= 2 else float("nan")

    fmins = [r["wear_fraction_min"] for r in good
             if isinstance(r.get("wear_fraction_min"), float)]
    fmaxs = [r["wear_fraction_max"] for r in good
             if isinstance(r.get("wear_fraction_max"), float)]

    # Base: first successful repetition; override key numeric fields with means
    rep = dict(good[0])
    rep["wear_fraction"] = mean_frac
    rep["wear_fraction_min"] = min(fmins) if fmins else None
    rep["wear_fraction_max"] = max(fmaxs) if fmaxs else None
    rep["repeat_std"] = std_frac
    rep["repeat_n"] = n
    rep["source_files"] = "; ".join(r.get("file", "") for r in good)

    # Recompute derived values from mean fraction
    nom_area = rep.get("ring_area_nominal_mm2")
    anal_area = rep.get("ring_area_analyzed_mm2")
    force = rep.get("force_N")
    if isinstance(nom_area, float) and mean_frac > 0:
        rep["wear_area_mm2"] = mean_frac * nom_area
        if isinstance(force, float):
            rep["resulting_contact_pressure_MPa"] = force / (mean_frac * nom_area)
    if isinstance(anal_area, float) and mean_frac > 0:
        rep["wear_area_analyzed_mm2"] = mean_frac * anal_area

    # Average geometry/calibration fields across reps
    for field in ("um_per_px", "ring_area_analyzed_mm2", "threshold"):
        vals = [r.get(field) for r in good if isinstance(r.get(field), float)]
        if vals:
            rep[field] = sum(vals) / len(vals)

    # Combine non-empty flag strings; note failed reps
    all_flags = [r.get("flags", "") for r in good if r.get("flags")]
    err_reps = [r.get("file", "?") for r in sub_results
                if not isinstance(r.get("wear_fraction"), float)]
    if err_reps:
        all_flags.append(f"failed reps: {', '.join(err_reps)}")
    rep["flags"] = "; ".join(all_flags) if all_flags else ""

    return rep


def _dispatch_subcommand(cmd: str, rest: list[str]) -> int:
    """Route subcommands to their own ArgumentParsers (no shared parser with positional args)."""
    if cmd == "manifest":
        ap = argparse.ArgumentParser(prog="ring_wear.py manifest")
        mani_sub = ap.add_subparsers(dest="manifest_action")
        p_init = mani_sub.add_parser("init", help="Manifest aus Dateinamen generieren")
        p_init.add_argument("folder")
        p_val = mani_sub.add_parser("validate", help="Manifest prüfen")
        p_val.add_argument("folder")
        a = ap.parse_args(rest)
        if a.manifest_action == "init":
            return _cmd_manifest_init(a)
        elif a.manifest_action == "validate":
            return _cmd_manifest_validate(a)
        else:
            ap.print_help()
            return 1

    if cmd == "repeat":
        ap = argparse.ArgumentParser(prog="ring_wear.py repeat")
        ap.add_argument("folder")
        ap.add_argument("-o", "--out", default="ring_wear_out/repeat")
        ap.add_argument("--neu-dir", default=None)
        ap.add_argument("--no-sensitivity", action="store_true")
        a = ap.parse_args(rest)
        return _cmd_repeat(a)

    if cmd == "before-after":
        ap = argparse.ArgumentParser(prog="ring_wear.py before-after")
        ap.add_argument("folder")
        ap.add_argument("-o", "--out", default="ring_wear_out/before_after")
        a = ap.parse_args(rest)
        return _cmd_before_after(a)

    print(f"Unknown subcommand: {cmd}", file=sys.stderr)
    return 1


def main(argv=None):
    # Manual dispatch BEFORE argparse to avoid Python 3.9+ subparser ambiguity:
    # when positional args (file paths) are mixed with subparsers, argparse
    # tries to match the first path as a subcommand choice and fails.
    if argv is None:
        argv = sys.argv[1:]

    _SUBCOMMANDS = {"manifest", "repeat", "before-after"}
    if argv and argv[0] in _SUBCOMMANDS:
        sys.exit(_dispatch_subcommand(argv[0], argv[1:]))

    # ── Main analysis (no subparsers — pure positional) ──────────────────────
    ap = argparse.ArgumentParser(
        description="Ring wear analysis. Subcommands: manifest, repeat, before-after",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("inputs", nargs="*", help="Bilddateien, Ordner oder Glob-Muster")
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
    ap.add_argument("--inner-diam-mm", type=float, default=3.0)
    ap.add_argument("--outer-diam-mm", type=float, default=8.0)
    ap.add_argument("--panel", action="store_true")
    ap.add_argument("--keep-annotations", action="store_true")
    ap.add_argument("--neu-dir", default=None)
    ap.add_argument("-o", "--out", default="ring_wear_out")
    ap.add_argument("--sensitivity-grid", default=None, metavar="JSON")
    ap.add_argument("--no-sensitivity", action="store_true")
    a = ap.parse_args(argv)

    if not a.inputs:
        ap.print_help()
        sys.exit(1)

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

    # Load sensitivity grid
    sens_grid, sens_best = None, None
    if not a.no_sensitivity:
        grid_path = None
        if a.sensitivity_grid:
            grid_path = Path(a.sensitivity_grid)
        else:
            # Auto-discover: look for sensitivity_grid.json next to first input
            first_parent = files[0].parent if files else Path(".")
            candidates = [
                first_parent / "sensitivity_grid.json",
                first_parent.parent / "sensitivity_grid.json",
                Path("sensitivity_grid.json"),
            ]
            for c in candidates:
                if c.exists():
                    grid_path = c
                    break
        if grid_path and grid_path.exists():
            try:
                sens_grid, sens_best = _sens.load_grid(grid_path)
                n_combos = (len(sens_grid.get("k_sigma", [])) *
                            len(sens_grid.get("tex_low_thr", [])) *
                            len(sens_grid.get("tex_min_rel", [])))
                print(f"[sensitivity] grid: {grid_path.name}  "
                      f"{n_combos} combinations  "
                      f"(assumption — ranges to be validated with repeat measurements)")
            except Exception as e:
                print(f"[sensitivity] WARNING: could not load {grid_path}: {e}")

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

    # Group input files by probe so that multiple repetitions of the same
    # experiment are merged into one output row (mean ± std).
    # All individual repetition analyses run internally for calibration;
    # only the aggregated result per probe appears in CSV / HTML / PPTX.
    grouped = _group_files_by_probe(files)
    rows = []

    for probe_key, probe_files in grouped.items():
        sub_results: list[dict] = []

        for f in probe_files:
            try:
                res = analyse(f, p, out, panel=a.panel, font=font,
                              sensitivity_grid=sens_grid, sensitivity_best=sens_best)

                res["_worn_abspath"] = str(f.resolve())

                mat = res.get("material", "")
                stem = Path(res["file"]).stem
                new_probe = _find_new_probe(mat, neu_dir)
                res["_new_probe_abspath"] = str(new_probe) if new_probe else None

                worn_dest = _copy_image_to_outdir(f, out, f"{stem}_worn{f.suffix}")
                new_dest  = _copy_image_to_outdir(new_probe, out, f"{stem}_new.jpg") if new_probe else None
                res["_worn_outdir"]     = worn_dest.name if worn_dest else None
                res["_new_probe_outdir"] = new_dest.name if new_dest  else None

                sub_results.append(res)
                ring_nom_val  = res.get("ring_area_nominal_mm2")
                ring_file     = res.get("sample_area_mm2")
                ring_analyzed = res.get("ring_area_analyzed_mm2")
                area_str = (
                    f"  nominal={ring_nom_val:.1f} mm² (OD={p.outer_diam_mm}/ID={p.inner_diam_mm} mm, "
                    f"filename={ring_file} mm²)  analyzed={ring_analyzed:.1f} mm² (image crop)"
                    if ring_nom_val and ring_file else ""
                )
                rep_tag = f"  [rep {len(sub_results)}/{len(probe_files)}]" if len(probe_files) > 1 else ""
                print(f"{f.name:40s} {res['wear_fraction']*100:5.1f} %  T=+{(res['threshold']-1)*100:4.1f} %  "
                      f"Seam: {res['seam_status']:<20s}{area_str}  {res['flags']}{rep_tag}")
            except Exception as e:
                sub_results.append({"file": f.name, "flags": f"ERROR: {e}"})
                print(f"{f.name:40s} ERROR: {e}")

        if len(probe_files) == 1:
            # Single measurement: pass through unchanged
            rows.append(sub_results[0])
        else:
            # Multiple repetitions: merge into one aggregated row
            agg = _aggregate_probe_results(probe_key, probe_files, sub_results)
            # Images / overlay come from the first successful repetition
            first_good = next((r for r in sub_results
                               if isinstance(r.get("wear_fraction"), float)), None)
            if first_good:
                for _k in ("_worn_abspath", "_new_probe_abspath",
                           "_worn_outdir", "_new_probe_outdir", "_fracs_grid"):
                    agg.setdefault(_k, first_good.get(_k))
            rows.append(agg)
            n_ok_rep = sum(1 for r in sub_results
                           if isinstance(r.get("wear_fraction"), float))
            std_str = (f"{agg['repeat_std']*100:.2f} pp"
                       if isinstance(agg.get("repeat_std"), float)
                          and not math.isnan(agg["repeat_std"])
                       else "n/a")
            print(f"  ↳ aggregate ({n_ok_rep}/{len(probe_files)} reps): "
                  f"mean={agg['wear_fraction']*100:.1f} %  ±{std_str}")

    # Rank stability report (requires sensitivity grid)
    if sens_grid and len(rows) >= 2:
        rs = _sens.rank_stability(rows)
        if rs["n_combos"] > 0:
            stable_str = "STABLE" if rs["stable"] else f"UNSTABLE ({rs['unstable_pairs']})"
            print(f"\n[sensitivity] rank stability across {rs['n_combos']} combos: "
                  f"{stable_str}  ({rs['n_pairs']} pairs checked)")
            for r_ in rows:
                if "_fracs_grid" in r_:
                    r_["rank_stable"] = rs["stable"]

    # Build CSV fieldnames — exclude internal (_-prefixed) keys to avoid list values in CSV
    keys = []
    for r_ in rows:
        keys += [k for k in r_ if k not in keys and not k.startswith("_")]
    with open(out / "results.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, delimiter=";", extrasaction="ignore")
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
