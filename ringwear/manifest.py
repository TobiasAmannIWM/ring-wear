"""ringwear.manifest — Manifest-Datenmodell, Parser, Validator, Init-Generator.

Manifest-CSV (Semikolon, UTF-8-BOM, Dezimalkomma):
    datei; probe; zustand; wiederholung; winkel_deg; sitzung; bemerkung

Spaltenwerte:
    zustand      ∈ {neu, vor, nach}   (neu = Neuprobe, vor/nach = vor/nach Versuch)
    wiederholung = 1, 2, 3 …          (Neupositionierung zwischen den Aufnahmen)
    winkel_deg   = 0 (normal) oder absichtliche Verdrehung für Verdrehtest
    sitzung      = Mikroskopsitzung (Datum o. Ä.) für Driftkontrolle

Fallback wenn kein Manifest existiert: Dateinamen parsen nach Schema
    <probe>_<zustand>_r<wiederholung>[_rot<+/-winkel>].<ext>
    z. B.  P017_vor_r2.tif   P003_neu_r1_rot+2.tif
Alte Konvention (T{N}_{Material}_{Force}N…) wird als Einzelaufnahme behandelt
    (probe=T{N}, zustand=inferred from neu/-Ordner, wiederholung=1).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Iterator

VALID_STATES = {"neu", "vor", "nach"}

MANIFEST_COLS = ["datei", "probe", "zustand", "wiederholung", "winkel_deg", "sitzung", "bemerkung"]

# Filename fallback: <probe>_<zustand>_r<rep>[_rot<sign><deg>]
_RE_NEW_PATTERN = re.compile(
    r"^(?P<probe>.+?)_(?P<zustand>neu|vor|nach)_r(?P<rep>\d+)(?:_rot(?P<deg>[+-]?\d+(?:\.\d+)?))?$",
    re.IGNORECASE,
)

# Old convention: T{N}_{Material}_{Force}N_{Area}mm2_ring  (single measurement)
_RE_OLD_PATTERN = re.compile(
    r"^(?P<probe>T\d+)_(?P<material>[^_]+)_(?P<force>\d+)N_(?P<area>\d+)mm2_ring$",
    re.IGNORECASE,
)


@dataclass
class ManifestRow:
    datei: str           # filename (stem + ext, no directory)
    probe: str           # unique probe ID
    zustand: str         # neu | vor | nach
    wiederholung: int    # 1-based repetition index
    winkel_deg: float    # deliberate rotation (0 = normal)
    sitzung: str         # session label (empty string if unknown)
    bemerkung: str       # free-text comment
    _source: str = field(default="manifest", repr=False)  # "manifest" | "filename" | "old_convention"


# ── Loading ────────────────────────────────────────────────────────────────────

def load_manifest(folder: Path, img_ext: frozenset[str] | None = None) -> tuple[list[ManifestRow], list[str]]:
    """Load manifest for *folder*.

    Returns (rows, warnings).
    If `manifest.csv` exists → parse it.
    Otherwise → fall back to filename parsing for every image file in *folder*.
    img_ext: set of lowercase extensions to consider (e.g. {".jpg", ".tif"}).
    """
    manifest_path = folder / "manifest.csv"
    if manifest_path.exists():
        return _load_csv(manifest_path)
    return _fallback_from_filenames(folder, img_ext or frozenset({".jpg", ".jpeg", ".tif", ".tiff", ".png", ".bmp"}))


def _load_csv(path: Path) -> tuple[list[ManifestRow], list[str]]:
    warnings: list[str] = []
    rows: list[ManifestRow] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        if reader.fieldnames is None:
            warnings.append(f"{path.name}: empty file")
            return rows, warnings
        missing = [c for c in MANIFEST_COLS if c not in reader.fieldnames]
        if missing:
            warnings.append(f"{path.name}: missing columns {missing}")
        for i, raw in enumerate(reader, start=2):
            datei = raw.get("datei", "").strip()
            probe = raw.get("probe", "").strip()
            zustand = raw.get("zustand", "").strip().lower()
            try:
                wiederholung = int(raw.get("wiederholung", "1") or "1")
            except ValueError:
                wiederholung = 1
                warnings.append(f"row {i}: wiederholung not int → 1")
            try:
                winkel_deg = float((raw.get("winkel_deg", "0") or "0").replace(",", "."))
            except ValueError:
                winkel_deg = 0.0
                warnings.append(f"row {i}: winkel_deg not numeric → 0")
            sitzung = raw.get("sitzung", "").strip()
            bemerkung = raw.get("bemerkung", "").strip()

            if not datei:
                warnings.append(f"row {i}: empty 'datei' — skipped")
                continue
            if not probe:
                warnings.append(f"row {i}: empty 'probe' for '{datei}'")
            if zustand not in VALID_STATES:
                warnings.append(f"row {i}: unknown zustand '{zustand}' for '{datei}'")

            rows.append(ManifestRow(
                datei=datei, probe=probe, zustand=zustand,
                wiederholung=wiederholung, winkel_deg=winkel_deg,
                sitzung=sitzung, bemerkung=bemerkung,
                _source="manifest",
            ))
    return rows, warnings


def _fallback_from_filenames(
    folder: Path,
    img_ext: frozenset[str],
) -> tuple[list[ManifestRow], list[str]]:
    warnings: list[str] = []
    rows: list[ManifestRow] = []
    files = sorted(f for f in folder.iterdir() if f.suffix.lower() in img_ext)
    for f in files:
        stem = f.stem
        row, w = _parse_stem(stem, f.name)
        rows.append(row)
        warnings.extend(w)
    return rows, warnings


def _parse_stem(stem: str, filename: str) -> tuple[ManifestRow, list[str]]:
    """Try new pattern, then old convention, then unknown fallback."""
    warnings: list[str] = []

    m = _RE_NEW_PATTERN.match(stem)
    if m:
        return ManifestRow(
            datei=filename,
            probe=m.group("probe"),
            zustand=m.group("zustand").lower(),
            wiederholung=int(m.group("rep")),
            winkel_deg=float(m.group("deg") or 0),
            sitzung="",
            bemerkung="",
            _source="filename",
        ), warnings

    m = _RE_OLD_PATTERN.match(stem)
    if m:
        return ManifestRow(
            datei=filename,
            probe=m.group("probe"),
            zustand="nach",   # worn ring → assumed post-test
            wiederholung=1,
            winkel_deg=0.0,
            sitzung="",
            bemerkung="old_convention",
            _source="old_convention",
        ), warnings

    # Unknown pattern — treat as single measurement, probe = stem
    warnings.append(
        f"'{filename}': does not match new pattern (<probe>_<zustand>_r<rep>) "
        f"or old convention (T{{N}}_…_ring) — treated as single measurement, probe='{stem}'"
    )
    return ManifestRow(
        datei=filename,
        probe=stem,
        zustand="nach",
        wiederholung=1,
        winkel_deg=0.0,
        sitzung="",
        bemerkung="unknown_pattern",
        _source="filename",
    ), warnings


# ── Validation ─────────────────────────────────────────────────────────────────

def validate(rows: list[ManifestRow], folder: Path | None = None) -> list[str]:
    """Return list of error/warning strings. Empty = clean."""
    errors: list[str] = []

    # Duplicate (datei) entries
    seen_datei: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r.datei in seen_datei:
            errors.append(
                f"Duplicate file entry '{r.datei}' at rows {seen_datei[r.datei]+1} and {i+1}"
            )
        else:
            seen_datei[r.datei] = i

    # Duplicate (probe, zustand, wiederholung, winkel_deg) → same measurement twice
    seen_key: dict[tuple, int] = {}
    for i, r in enumerate(rows):
        key = (r.probe, r.zustand, r.wiederholung, r.winkel_deg)
        if key in seen_key:
            errors.append(
                f"Duplicate measurement key {key} for files "
                f"'{rows[seen_key[key]].datei}' and '{r.datei}'"
            )
        else:
            seen_key[key] = i

    # Unknown state
    for r in rows:
        if r.zustand not in VALID_STATES:
            errors.append(f"'{r.datei}': unknown zustand '{r.zustand}' (must be neu/vor/nach)")

    # Files missing on disk
    if folder is not None:
        for r in rows:
            if not (folder / r.datei).exists():
                errors.append(f"File listed in manifest not found on disk: '{r.datei}'")

    return errors


# ── Init Generator ─────────────────────────────────────────────────────────────

def init_manifest(folder: Path, img_ext: frozenset[str] | None = None) -> tuple[Path, list[str]]:
    """Generate a manifest.csv from filenames in *folder* for manual editing.

    Returns (path_written, warnings).
    Does NOT overwrite an existing manifest.csv — raises FileExistsError instead.
    """
    _ext = img_ext or frozenset({".jpg", ".jpeg", ".tif", ".tiff", ".png", ".bmp"})
    out_path = folder / "manifest.csv"
    if out_path.exists():
        raise FileExistsError(
            f"{out_path} already exists. Delete or rename it before running 'manifest init'."
        )

    rows, warnings = _fallback_from_filenames(folder, _ext)
    if not rows:
        warnings.append(f"No image files found in {folder}")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLS, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({
                "datei": r.datei,
                "probe": r.probe,
                "zustand": r.zustand,
                "wiederholung": r.wiederholung,
                "winkel_deg": str(r.winkel_deg).replace(".", ","),
                "sitzung": r.sitzung,
                "bemerkung": r.bemerkung,
            })
    return out_path, warnings
