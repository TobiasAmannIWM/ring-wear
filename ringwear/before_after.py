"""ringwear.before_after - Vorher-Nachher-Vergleich (Phase 3).

Paart vor/nach-Aufnahmen derselben Probe und berechnet:
  delta = wear_fraction(nach) - wear_fraction(vor)

Wenn mehrere Wiederholungen existieren, werden Mittelwerte verwendet.
Fehlende vor-Aufnahmen: delta = NaN (Probe erscheint trotzdem in Ausgabe).

Ausgabe: BeforeAfterResult mit einer ProbeDelta-Zeile pro Probe.
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
class ProbeImages:
    """Alle Bilder einer Probe, aufgeteilt nach Zustand."""
    probe: str
    vor_files: list[str]   # Pfade oder Dateinamen der vor-Aufnahmen
    nach_files: list[str]  # Pfade oder Dateinamen der nach-Aufnahmen


@dataclass
class ProbeDelta:
    probe: str
    vor_mean: float | None     # Mittelwert wear_fraction (vor)
    nach_mean: float | None    # Mittelwert wear_fraction (nach)
    delta: float | None        # nach_mean - vor_mean; None wenn vor fehlt
    vor_n: int                 # Anzahl gültiger vor-Bilder
    nach_n: int                # Anzahl gültiger nach-Bilder
    vor_files: list[str]
    nach_files: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class BeforeAfterResult:
    probe_deltas: list[ProbeDelta]
    n_paired: int        # Proben mit sowohl vor als auch nach
    n_nach_only: int     # Proben nur mit nach-Aufnahmen (kein vor vorhanden)
    n_vor_only: int      # Proben nur mit vor-Aufnahmen (kein nach vorhanden)
    warnings: list[str]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _analyse_files(
    paths: list[Path],
    params: Params,
    out: Path,
) -> list[float]:
    """Analysiert mehrere Bilder; gibt nur gültige (nicht-NaN) wear_fractions zurück."""
    fracs: list[float] = []
    for p in paths:
        try:
            img_out = out / p.stem
            img_out.mkdir(parents=True, exist_ok=True)
            res = analyse(p, params, img_out, panel=False, sensitivity_grid=None)
            frac = res["wear_fraction"]
            if math.isnan(frac):
                continue
            fracs.append(frac)
        except Exception:
            pass
    return fracs


# ── Main function ───────────────────────────────────────────────────────────────

def run_before_after(
    folder: Path | str,
    params: Params,
    out: Path | str,
) -> BeforeAfterResult:
    """Paart vor/nach-Aufnahmen und berechnet Deltas.

    Erkennt Paarungen über das Manifest (wenn vorhanden) oder den Dateinamen.
    folder: Ordner mit den Bildern (enthält vor- und nach-Aufnahmen).
    """
    folder = Path(folder)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    rows, load_warnings = M.load_manifest(folder)

    # Gruppiere nach (probe, zustand)
    groups: dict[str, dict[str, list[M.ManifestRow]]] = {}
    for row in rows:
        if row.zustand not in {"vor", "nach"}:
            continue  # 'neu' wird hier nicht ausgewertet
        groups.setdefault(row.probe, {}).setdefault(row.zustand, []).append(row)

    all_probes = sorted(groups.keys())
    global_warnings = list(load_warnings)

    probe_deltas: list[ProbeDelta] = []
    n_paired = n_nach_only = n_vor_only = 0

    for probe in all_probes:
        z = groups[probe]
        vor_rows = z.get("vor", [])
        nach_rows = z.get("nach", [])

        vor_paths = [folder / r.datei for r in vor_rows]
        nach_paths = [folder / r.datei for r in nach_rows]

        # Existenzcheck
        vor_paths = [p for p in vor_paths if p.exists()]
        nach_paths = [p for p in nach_paths if p.exists()]

        vor_fracs = _analyse_files(vor_paths, params, out / "vor")
        nach_fracs = _analyse_files(nach_paths, params, out / "nach")

        vor_mean = float(np.mean(vor_fracs)) if vor_fracs else None
        nach_mean = float(np.mean(nach_fracs)) if nach_fracs else None
        delta = (nach_mean - vor_mean) if (vor_mean is not None and nach_mean is not None) else None

        pw: list[str] = []
        if not vor_fracs and vor_rows:
            pw.append(f"{probe}: vor-Bilder vorhanden aber nicht auswertbar")
        if not nach_fracs and nach_rows:
            pw.append(f"{probe}: nach-Bilder vorhanden aber nicht auswertbar")

        # Count based on manifest rows (what was intended), not analysis success
        has_vor  = len(vor_rows) > 0
        has_nach = len(nach_rows) > 0
        if has_vor and has_nach:
            n_paired += 1
        elif has_nach:
            n_nach_only += 1
        elif has_vor:
            n_vor_only += 1

        probe_deltas.append(ProbeDelta(
            probe=probe,
            vor_mean=vor_mean,
            nach_mean=nach_mean,
            delta=delta,
            vor_n=len(vor_fracs),
            nach_n=len(nach_fracs),
            vor_files=[p.name for p in vor_paths],
            nach_files=[p.name for p in nach_paths],
            warnings=pw,
        ))

    return BeforeAfterResult(
        probe_deltas=probe_deltas,
        n_paired=n_paired,
        n_nach_only=n_nach_only,
        n_vor_only=n_vor_only,
        warnings=global_warnings,
    )


def write_before_after_csv(result: BeforeAfterResult, out: Path) -> Path:
    """Schreibt Ergebnisse als CSV (Semikolon, Dezimalkomma, UTF-8-BOM)."""
    import csv

    p = out / "before_after_report.csv"
    with p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "probe",
            "vor_n", "vor_wear_fraction_mean",
            "nach_n", "nach_wear_fraction_mean",
            "delta_wear_fraction",
            "vor_files", "nach_files",
            "warnings",
        ])
        for d in result.probe_deltas:
            w.writerow([
                d.probe,
                d.vor_n,
                f"{d.vor_mean:.4f}".replace(".", ",") if d.vor_mean is not None else "",
                d.nach_n,
                f"{d.nach_mean:.4f}".replace(".", ",") if d.nach_mean is not None else "",
                f"{d.delta:.4f}".replace(".", ",") if d.delta is not None else "",
                "|".join(d.vor_files),
                "|".join(d.nach_files),
                "; ".join(d.warnings),
            ])
    return p


def print_report(r: BeforeAfterResult) -> None:
    print(f"\nBefore-After Report  ({r.n_paired} paired, "
          f"{r.n_nach_only} nach-only, {r.n_vor_only} vor-only)")
    print(f"{'Probe':<20} {'vor':>8} {'nach':>8} {'delta':>8}  files")
    print("-" * 70)
    for d in r.probe_deltas:
        vor_s  = f"{d.vor_mean*100:6.1f}%" if d.vor_mean  is not None else "   n/a "
        nach_s = f"{d.nach_mean*100:6.1f}%" if d.nach_mean is not None else "   n/a "
        dlt_s  = f"{d.delta*100:+6.1f}pp"  if d.delta    is not None else "   n/a "
        n_vor  = f"(n={d.vor_n})" if d.vor_n  else ""
        n_nach = f"(n={d.nach_n})" if d.nach_n else ""
        print(f"{d.probe:<20} {vor_s}{n_vor:>5} {nach_s}{n_nach:>5} {dlt_s}")
        for w in d.warnings:
            print(f"  [WARN] {w}")
    if r.warnings:
        print()
        for w in r.warnings:
            print(f"[WARN] {w}")
