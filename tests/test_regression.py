"""Regressionstests: sichern das Verhalten der Referenzauswertung ab.

Referenzwerte stammen aus der validierten Auswertung (siehe CLAUDE.md).
Nicht stillschweigend anpassen – Änderungen begründen und in CHANGELOG.md
dokumentieren.
"""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import ring_wear as rw

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "reference"
ANN = ROOT / "data" / "annotated"

EXPECTED = {
    # stem: (wear_fraction, um_per_px, ring_area_analyzed_mm2)
    # Namensschema: T{N}_{Material}_{Force}N_{Area}mm2_ring
    # Werte kalibriert 2026-11-13.
    # ring_area_analyzed_mm2: sichtbarer Bildausschnitt (nicht die volle 43mm²-Kontaktfläche).
    # Nominale Ringfläche π/4·(8²−3²)=43,2mm² wird aus Params.outer/inner_diam_mm berechnet.
    "T10_INC718_810N_43mm2_ring":  (0.178, 3.378, 6.04),
    "T9_INC625M_810N_43mm2_ring":  (0.129, 3.378, 6.08),
    "T7_INC718_1620N_43mm2_ring":  (0.079, 3.378, 5.95),
    "T3_INC625M_1620N_43mm2_ring": (0.042, 3.378, 5.96),
}
# Dateiendung der Referenzbilder
_REF_EXT = ".jpg"
TOL_FRAC = 0.015      # ±1,5 Prozentpunkte
TOL_UPX = 0.02        # ±2 %
TOL_AREA = 0.30       # ±0,30 mm² für ring_area_analyzed


@pytest.fixture(scope="module")
def params():
    return rw.Params()


def run(path, params, tmp_path):
    return rw.analyse(Path(path), params, Path(tmp_path), panel=False,
                      font=rw.ImageFont.load_default())


@pytest.mark.parametrize("name", list(EXPECTED))
def test_reference_values(name, params, tmp_path):
    frac, upx, area = EXPECTED[name]
    res = run(REF / f"{name}{_REF_EXT}", params, tmp_path)
    assert abs(res["wear_fraction"] - frac) <= TOL_FRAC, res
    assert abs(res["um_per_px"] - upx) / upx <= TOL_UPX, res
    assert abs(res["ring_area_analyzed_mm2"] - area) <= TOL_AREA, res
    assert (tmp_path / f"{name}_overlay.png").exists()


@pytest.mark.parametrize("clean,annotated", [
    ("T10_INC718_810N_43mm2_ring", "T10_INC718_810N_43mm2_ring_annotated"),
    ("T9_INC625M_810N_43mm2_ring", "T9_INC625M_810N_43mm2_ring_annotated"),
])
def test_annotations_removed(clean, annotated, params, tmp_path):
    a = run(REF / f"{clean}{_REF_EXT}", params, tmp_path)
    b = run(ANN / f"{annotated}.png", params, tmp_path)
    assert abs(a["wear_fraction"] - b["wear_fraction"]) <= 0.01


@pytest.mark.parametrize("factor", [0.7, 1.5])
def test_scale_invariance(factor, params, tmp_path):
    src = Image.open(REF / f"T10_INC718_810N_43mm2_ring{_REF_EXT}").convert("RGB")
    p = tmp_path / f"T10_INC718_810N_43mm2_ring_x{factor}.png"
    src.resize((int(src.width * factor), int(src.height * factor)), Image.LANCZOS).save(p)
    a = run(REF / f"T10_INC718_810N_43mm2_ring{_REF_EXT}", params, tmp_path)
    b = run(p, params, tmp_path)
    assert abs(a["wear_fraction"] - b["wear_fraction"]) <= 0.01


def test_exposure_invariance(params, tmp_path):
    arr = np.array(Image.open(REF / f"T7_INC718_1620N_43mm2_ring{_REF_EXT}").convert("RGB")).astype(float)
    p = tmp_path / "T7_INC718_1620N_43mm2_ring_dark.png"
    Image.fromarray(np.clip(arr * 0.8, 0, 255).astype(np.uint8)).save(p)
    a = run(REF / f"T7_INC718_1620N_43mm2_ring{_REF_EXT}", params, tmp_path)
    b = run(p, params, tmp_path)
    assert abs(a["wear_fraction"] - b["wear_fraction"]) <= 0.01


_RING_FILES = [f"{s}{_REF_EXT}" for s in EXPECTED]

def test_ranking(params, tmp_path):
    f = [run(REF / name, params, tmp_path)["wear_fraction"] for name in _RING_FILES]
    assert f[0] > f[1] > f[2] > f[3]


# --------------------------------------------------------------------------- #
# Phase 0.5 — method band tests
# --------------------------------------------------------------------------- #
_GRID_PATH = ROOT / "sensitivity_grid.json"


@pytest.fixture(scope="module")
def grid():
    if not _GRID_PATH.exists():
        pytest.skip("sensitivity_grid.json not found")
    return rw.sensitivity.load_grid(_GRID_PATH)


def _run_with_band(path, params, tmp_path, grid_tuple):
    sens_grid, sens_best = grid_tuple
    return rw.analyse(Path(path), params, Path(tmp_path), panel=False,
                      font=rw.ImageFont.load_default(),
                      sensitivity_grid=sens_grid, sensitivity_best=sens_best)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_sensitivity_method_band(name, params, tmp_path, grid):
    """wear_fraction_min ≤ wear_fraction ≤ wear_fraction_max for all reference images."""
    res = _run_with_band(REF / f"{name}{_REF_EXT}", params, tmp_path, grid)
    frac = res["wear_fraction"]
    fmin = res["wear_fraction_min"]
    fmax = res["wear_fraction_max"]
    assert fmin is not None, "wear_fraction_min should not be None when grid is supplied"
    assert fmax is not None, "wear_fraction_max should not be None when grid is supplied"
    assert fmin <= frac + 1e-6, f"fmin={fmin} > frac={frac}"
    assert fmax >= frac - 1e-6, f"fmax={fmax} < frac={frac}"
    assert fmax >= fmin, f"fmax={fmax} < fmin={fmin}"
    assert res["method_band_pp"] is not None
    assert res["_fracs_grid"] is not None
    assert len(res["_fracs_grid"]) == res.get("_n_combos", len(res["_fracs_grid"]))


def test_sensitivity_ranking_stable(params, tmp_path, grid):
    """Ranking T10 > T9 > T7 > T3 must hold across all grid combinations."""
    rows = [_run_with_band(REF / name, params, tmp_path, grid)
            for name in _RING_FILES]
    result = rw.sensitivity.rank_stability(rows)
    assert result["stable"], (
        f"Ranking unstable for pairs: {result['unstable_pairs']} "
        f"across {result['n_combos']} grid combinations"
    )
