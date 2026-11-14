"""ringwear.repeat - Wiederholbarkeitsanalyse (Phase 2).

Varianzkomponenten via einfaktorieller ANOVA (Probe als Faktor):
  s_r  = Wiederholstandardabweichung (innerhalb Probe, gepoolt)
  s_p  = Streuung zwischen Proben (Fertigung); auf 0 gesetzt wenn negativ
  ICC  = s_p² / (s_p² + s_r²)

Nachweisgrenze (LOD):
  Einzelmessung:    LOD = f0 + t(0.95, df) * sqrt(s_p² + s_r²)
  k Wiederholungen: LOD = f0 + t(0.95, df) * sqrt(s_p² + s_r²/k)

f0 = Mittelwert der Neuproben (wear_fraction ≈ 0 für unverschlissene Ringe).
Wenn keine Neuproben vorhanden: f0 = 0 mit Warnung.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

from .core import Params, IMG_EXT, analyse
from . import manifest as M


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ProbeStats:
    probe: str
    zustand: str
    n: int                    # Anzahl Wiederholungen
    mean: float               # Mittelwert wear_fraction
    std: float                # Standardabweichung (n-1)
    ci_lo: float              # 95-%-KI untere Grenze
    ci_hi: float              # 95-%-KI obere Grenze
    ci_source: str            # "eigen" | "kalibrierung"
    values: list[float] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass
class RepeatResult:
    probe_stats: list[ProbeStats]
    s_r: float                # Wiederholstandardabweichung (gepoolt)
    s_p: float                # Probenstreuung (>=0)
    s_p_negative_clamped: bool
    icc: float                # Intraklassen-Korrelation
    df_within: int            # Freiheitsgrade innerhalb (für t-Verteilung)
    n_probes: int
    n_total: int
    lod_single: float | None  # LOD Einzelmessung (braucht f0)
    lod_k3: float | None      # LOD bei k=3 Wiederholungen
    f0: float | None          # Mittelwert Neuproben
    f0_source: str            # "measured" | "assumed_zero" | "none"
    warnings: list[str]


# ── Core analysis ──────────────────────────────────────────────────────────────

def run_repeat(
    folder: Path,
    params: Params,
    out: Path,
    *,
    sensitivity_grid: dict | None = None,
    sensitivity_best: dict | None = None,
    neu_folder: Path | None = None,
) -> RepeatResult:
    """Analyse all worn-probe images in *folder* grouped by probe via manifest.

    Parameters
    ----------
    folder        : folder with images + optional manifest.csv
    params        : analysis parameters
    out           : output directory for per-image overlays
    sensitivity_grid / sensitivity_best : passed through to analyse()
    neu_folder    : folder with new-probe images (zustand='neu') for f0
    """
    warnings: list[str] = []

    # ── Load manifest ──────────────────────────────────────────────────────────
    rows, mw = M.load_manifest(folder)
    warnings.extend(mw)
    errors = M.validate(rows, folder)
    for e in errors:
        warnings.append(f"Manifest validation: {e}")

    # ── Analyse every image ────────────────────────────────────────────────────
    results_by_probe: dict[str, list[tuple[str, float]]] = {}
    neu_values: list[float] = []

    from PIL import ImageFont
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except OSError:
            font = ImageFont.load_default()

    # If no manifest rows, fall back to all images in folder
    if not rows:
        img_files = sorted(f for f in folder.iterdir() if f.suffix.lower() in IMG_EXT)
        for f in img_files:
            row, fw = M._parse_stem(f.stem, f.name)
            rows.append(row)
            warnings.extend(fw)

    for mrow in rows:
        img_path = folder / mrow.datei
        if not img_path.exists():
            warnings.append(f"Image not found: {mrow.datei} - skipped")
            continue
        try:
            res = analyse(img_path, params, out, font=font,
                          sensitivity_grid=sensitivity_grid,
                          sensitivity_best=sensitivity_best)
            frac = res["wear_fraction"]
        except Exception as e:
            warnings.append(f"{mrow.datei}: analysis error - {e}")
            continue

        if math.isnan(frac):
            warnings.append(f"{mrow.datei}: wear_fraction = NaN (ring detection failed) - excluded")
            continue
        if mrow.zustand == "neu":
            neu_values.append(frac)
        else:
            key = mrow.probe
            results_by_probe.setdefault(key, [])
            results_by_probe[key].append((mrow.datei, frac))

    # Also scan neu_folder if provided
    if neu_folder and neu_folder.is_dir():
        neu_rows, nw = M.load_manifest(neu_folder)
        warnings.extend(nw)
        if not neu_rows:
            neu_files = sorted(f for f in neu_folder.iterdir() if f.suffix.lower() in IMG_EXT)
            for f in neu_files:
                try:
                    res = analyse(f, params, out, font=font)
                    neu_values.append(res["wear_fraction"])
                except Exception as e:
                    warnings.append(f"neu/{f.name}: {e}")
        else:
            for nr in neu_rows:
                if nr.zustand != "neu":
                    continue
                img_path = neu_folder / nr.datei
                if not img_path.exists():
                    continue
                try:
                    res = analyse(img_path, params, out, font=font)
                    neu_values.append(res["wear_fraction"])
                except Exception as e:
                    warnings.append(f"neu/{nr.datei}: {e}")

    # ── f0: mean of new probes ─────────────────────────────────────────────────
    if neu_values:
        f0 = float(np.mean(neu_values))
        f0_source = "measured"
    else:
        f0 = 0.0
        f0_source = "assumed_zero"
        warnings.append("No new-probe images found - f0 assumed 0.0 (LOD conservative)")

    # ── Per-probe statistics ───────────────────────────────────────────────────
    probe_stats: list[ProbeStats] = []
    ss_within = 0.0
    df_within = 0

    for probe, entries in sorted(results_by_probe.items()):
        files = [e[0] for e in entries]
        vals = [e[1] for e in entries]
        n = len(vals)
        mean = float(np.mean(vals))
        if n >= 2:
            std = float(np.std(vals, ddof=1))
            t95 = _t95(n - 1)
            ci_lo = mean - t95 * std / math.sqrt(n)
            ci_hi = mean + t95 * std / math.sqrt(n)
            ci_src = "eigen"
            ss_within += (n - 1) * std ** 2
            df_within += n - 1
        else:
            std = float("nan")
            ci_lo = ci_hi = float("nan")
            ci_src = "kalibrierung"
            warnings.append(f"Probe {probe}: only 1 measurement - CI from calibration s_r (not yet available)")

        probe_stats.append(ProbeStats(
            probe=probe, zustand="nach", n=n,
            mean=mean, std=std,
            ci_lo=ci_lo, ci_hi=ci_hi,
            ci_source=ci_src,
            values=vals, files=files,
        ))

    # ── ANOVA variance components ──────────────────────────────────────────────
    n_probes = len(probe_stats)
    n_total = sum(ps.n for ps in probe_stats)

    if df_within > 0:
        s_r2 = ss_within / df_within
        s_r = math.sqrt(s_r2)
    else:
        s_r2 = float("nan")
        s_r = float("nan")
        warnings.append("Not enough within-probe repetitions to estimate s_r")

    # Between-probe variance (Method of Moments)
    s_p2_clamped = False
    if n_probes >= 2 and not math.isnan(s_r2):
        grand_mean = float(np.mean([ps.mean for ps in probe_stats]))
        ss_between = sum(ps.n * (ps.mean - grand_mean) ** 2 for ps in probe_stats)
        df_between = n_probes - 1
        ms_between = ss_between / df_between
        n_avg = n_total / n_probes  # simplified (balanced design assumed)
        s_p2_raw = (ms_between - s_r2) / n_avg
        if s_p2_raw < 0:
            s_p2 = 0.0
            s_p2_clamped = True
            warnings.append(f"s_p² estimate was negative ({s_p2_raw:.6f}) - clamped to 0 (common with few probes)")
        else:
            s_p2 = s_p2_raw
        s_p = math.sqrt(s_p2)
        icc = s_p2 / (s_p2 + s_r2) if (s_p2 + s_r2) > 0 else 0.0
    else:
        s_p = float("nan")
        icc = float("nan")
        warnings.append("Need >=2 probes to estimate s_p and ICC")

    # ── LOD ───────────────────────────────────────────────────────────────────
    if not math.isnan(s_r) and not math.isnan(s_p) and df_within > 0:
        t95_df = _t95(df_within)
        total_var = s_p ** 2 + s_r ** 2
        lod_single = f0 + t95_df * math.sqrt(total_var)
        lod_k3 = f0 + t95_df * math.sqrt(s_p ** 2 + s_r ** 2 / 3)
    else:
        lod_single = lod_k3 = None

    return RepeatResult(
        probe_stats=probe_stats,
        s_r=s_r, s_p=s_p,
        s_p_negative_clamped=s_p2_clamped,
        icc=icc,
        df_within=df_within,
        n_probes=n_probes,
        n_total=n_total,
        lod_single=lod_single,
        lod_k3=lod_k3,
        f0=f0,
        f0_source=f0_source,
        warnings=warnings,
    )


# ── Report ─────────────────────────────────────────────────────────────────────

def print_report(r: RepeatResult) -> None:
    print("\n" + "=" * 60)
    print("REPEAT MEASUREMENT ANALYSIS")
    print("=" * 60)
    print(f"  Probes:          {r.n_probes}")
    print(f"  Total images:    {r.n_total}")
    print(f"  s_r  (repeat):   {r.s_r*100:.2f} pp"
          + (" [NOTE: only 1 probe]" if r.n_probes < 2 else ""))
    if not math.isnan(r.s_p):
        clamp_note = "  (negative → clamped to 0)" if r.s_p_negative_clamped else ""
        print(f"  s_p  (between):  {r.s_p*100:.2f} pp{clamp_note}")
        print(f"  ICC:             {r.icc:.3f}")
    if r.lod_single is not None:
        print(f"  f0 ({r.f0_source}):   {(r.f0 or 0)*100:.2f} %")
        print(f"  LOD (k=1):       {r.lod_single*100:.2f} %  (single measurement)")
        print(f"  LOD (k=3):       {r.lod_k3*100:.2f} %  (mean of 3 repeats)")
    print()
    print("  Per-probe results:")
    for ps in r.probe_stats:
        ci_str = (f"  95%-CI [{ps.ci_lo*100:.1f}, {ps.ci_hi*100:.1f}] ({ps.ci_source})"
                  if not math.isnan(ps.ci_lo) else f"  CI: {ps.ci_source}")
        print(f"    {ps.probe:12s}  n={ps.n}  mean={ps.mean*100:.1f}%"
              + (f"  std={ps.std*100:.2f}pp" if not math.isnan(ps.std) else "")
              + ci_str)
    if r.warnings:
        print()
        print("  Warnings:")
        for w in r.warnings:
            print(f"    [!] {w}")
    print("=" * 60)


def write_repeat_csv(r: RepeatResult, out: Path) -> Path:
    """Write per-probe summary CSV."""
    import csv
    path = out / "repeat_summary.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["probe", "n", "mean_%", "std_pp", "ci_lo_%", "ci_hi_%",
                    "ci_source", "files"])
        for ps in r.probe_stats:
            w.writerow([
                ps.probe, ps.n,
                f"{ps.mean*100:.4f}".replace(".", ","),
                f"{ps.std*100:.4f}".replace(".", ",") if not math.isnan(ps.std) else "",
                f"{ps.ci_lo*100:.4f}".replace(".", ",") if not math.isnan(ps.ci_lo) else "",
                f"{ps.ci_hi*100:.4f}".replace(".", ",") if not math.isnan(ps.ci_hi) else "",
                ps.ci_source,
                "; ".join(ps.files),
            ])
        w.writerow([])
        w.writerow(["s_r_pp", f"{r.s_r*100:.4f}".replace(".", ",")])
        w.writerow(["s_p_pp", f"{r.s_p*100:.4f}".replace(".", ",") if not math.isnan(r.s_p) else ""])
        w.writerow(["icc",    f"{r.icc:.4f}".replace(".", ",") if not math.isnan(r.icc) else ""])
        w.writerow(["lod_single_%", f"{r.lod_single*100:.4f}".replace(".", ",") if r.lod_single else ""])
        w.writerow(["lod_k3_%",     f"{r.lod_k3*100:.4f}".replace(".", ",") if r.lod_k3 else ""])
        w.writerow(["f0_%",         f"{(r.f0 or 0)*100:.4f}".replace(".", ",")])
        w.writerow(["f0_source",    r.f0_source])
    return path


# ── Helper ─────────────────────────────────────────────────────────────────────

def _t95(df: int) -> float:
    """Two-sided t critical value at 95 % confidence for given df."""
    # Tabulated values for common df; falls back to 1.96 for large df
    _TABLE = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
              6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
              15: 2.131, 20: 2.086, 30: 2.042, 60: 2.000}
    if df <= 0:
        return float("nan")
    for threshold, t in sorted(_TABLE.items()):
        if df <= threshold:
            return t
    return 1.96
